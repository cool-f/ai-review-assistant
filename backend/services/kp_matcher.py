"""
KPMatcher — 关键词匹配服务

将解答文本通过中文分词 (jieba) 提取关键词，与已有知识点进行关键词命中率
计算，返回 top-3 匹配结果 (命中率 > 0.3)。

匹配方法标记为 'keyword'。
"""

import logging
import re

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from backend.models import KnowledgePoint


logger = logging.getLogger(__name__)


# ── jieba 导入 ───────────────────────────────────
try:
    import jieba

    HAS_JIEBA = True
except ImportError:
    HAS_JIEBA = False
    logger.warning(
        "jieba 未安装，KPMatcher 退化为简易字符 bigram 分词。"
        "请运行: pip install jieba"
    )


# ── 中文停用词表 ──────────────────────────────────
_STOP_WORDS: set[str] = {
    # 虚词 / 助词
    "的", "了", "在", "是", "有", "和", "就", "不", "人", "都", "一",
    "上", "也", "很", "到", "说", "要", "去", "会", "着", "被", "把",
    "从", "对", "向", "让", "用", "能", "将", "已", "还", "又", "再",
    "才", "刚", "便", "却", "只", "可", "并", "中", "里", "与", "及",
    "或", "但", "而", "且", "因", "所", "以", "之", "其", "为", "于",
    "则", "者", "此", "该", "各", "某", "每", "比", "较", "更", "最",
    # 代词
    "我", "你", "他", "她", "它", "们", "这", "那", "哪", "谁", "什么",
    "怎么", "怎样", "如何", "为什么", "多少", "几", "自己", "大家",
    "别人", "这个", "那个", "这些", "那些", "这里", "那里", "这样",
    "那样", "这么", "那么",
    # 连词 / 介词 / 副词
    "没有", "可以", "还是", "只是", "但是", "因为", "所以", "如果",
    "虽然", "而且", "或者", "不过", "然后", "之后", "之前", "以后",
    "以前", "时候", "已经", "正在", "一直", "总是", "经常", "可能",
    "应该", "需要", "必须", "一定", "当然", "其实", "确实", "真的",
    "不是", "不会", "不能", "不要", "不用", "是否", "吗", "呢", "吧",
    "啊", "哦", "嗯", "哈",
    # 量词 / 数词上下文
    "一个", "一种", "一些", "一点", "一下", "一次", "这个", "每个",
    "任何", "所有", "整个", "全部",
}


# 最小关键词长度
_MIN_KEYWORD_LEN = 2


class KPMatcher:
    """
    关键词匹配服务

    职责:
      - 使用 jieba 对解答文本进行中文分词
      - 过滤停用词和噪声词，提取关键词集合
      - 对每个知识点计算关键词命中率
      - 返回命中率 > 0.3 的 top-3 知识点

    Usage:
        matcher = KPMatcher(db)
        matches = await matcher.match(solution_text)
        # => [{"knowledge_point_id": ..., "title": ..., "relevance_score": 0.75}, ...]
    """

    def __init__(self, db: AsyncSession):
        """
        Args:
            db: 数据库会话 (用于查询知识点)
        """
        self.db = db

    # ── 公开接口 ──────────────────────────────────

    async def match(self, solution_text: str) -> list[dict]:
        """
        将解答文本与所有知识点进行关键词匹配

        Args:
            solution_text: 解答文本 (含题目 + 答案)

        Returns:
            [{
                "knowledge_point_id": str,
                "title": str,
                "relevance_score": float,   # 命中率, 0.0 ~ 1.0
            }, ...]
            按 relevance_score 降序排列，最多 3 条 (且 score > 0.3)
        """
        # 1. 提取解答的关键词
        solution_keywords = self._extract_keywords(solution_text)
        if not solution_keywords:
            logger.debug("KPMatcher: 解答文本中未提取到有效关键词")
            return []

        # 2. 查询所有知识点
        result = await self.db.execute(
            select(KnowledgePoint).order_by(KnowledgePoint.created_at)
        )
        all_kps = list(result.scalars().all())

        if not all_kps:
            logger.debug("KPMatcher: 数据库中没有知识点可供匹配")
            return []

        # 3. 计算每个知识点的关键词命中率
        scored: list[dict] = []
        for kp in all_kps:
            kp_text = f"{kp.title} {kp.content}"
            kp_keywords = self._extract_keywords(kp_text)
            if not kp_keywords:
                continue

            common = solution_keywords & kp_keywords
            hit_rate = len(common) / len(solution_keywords)

            if hit_rate > 0.3:
                scored.append({
                    "knowledge_point_id": kp.id,
                    "title": kp.title,
                    "relevance_score": round(hit_rate, 4),
                })

        # 4. 按命中率降序排列，取前 3
        scored.sort(key=lambda x: x["relevance_score"], reverse=True)

        top3 = scored[:3]
        logger.debug(
            "KPMatcher: %d 个匹配 (关键词数=%d, 扫描KP=%d)",
            len(top3),
            len(solution_keywords),
            len(all_kps),
        )

        return top3

    # ── 关键词提取 ────────────────────────────────

    def _extract_keywords(self, text: str) -> set[str]:
        """
        从文本中提取有意义的关键词集合

        流程:
          1. 分词 (jieba 或 fallback bigram)
          2. 清洗: 去空白、统一小写
          3. 过滤: 长度不足、停用词、纯数字/标点
        """
        if not text or not text.strip():
            return set()

        if HAS_JIEBA:
            words = jieba.cut(text)
        else:
            words = self._fallback_segment(text)

        keywords: set[str] = set()
        for w in words:
            w = w.strip()
            if len(w) < _MIN_KEYWORD_LEN:
                continue
            if w in _STOP_WORDS:
                continue
            if self._is_noise(w):
                continue
            keywords.add(w)

        return keywords

    # ── 噪声过滤 ──────────────────────────────────

    @staticmethod
    def _is_noise(word: str) -> bool:
        """
        判断一个词是否为噪声 (纯数字、纯标点、无意义组合)

        允许: 中英混合术语 ("L2正则化", "ReLU激活")
        拒绝: 纯标点、纯空白、纯数字（长度 <= 4 的数字可能是页码）
        """
        # 纯标点 / 空白
        if re.fullmatch(r"[]\s\.,;:!?，。；：！？、""''「」[【】()（）/\\|@#$%^&*+=<>`~-]+", word):
            return True
        # 纯数字（短数字很可能是序号/页码）
        if re.fullmatch(r"\d+", word):
            return len(word) <= 4
        return False

    # ── Fallback 分词 ─────────────────────────────

    @staticmethod
    def _fallback_segment(text: str) -> list[str]:
        """
        jieba 不可用时的简易分词

        策略: 在标点/空白处切分 + 生成字符 bigram 作为补充
        """
        # 先按常见分隔符切分
        segments = re.split(r"[]\s,\.;:!?，。；：！？、""''「」[【】()（）/\\]+", text)
        words: list[str] = []

        for seg in segments:
            seg = seg.strip()
            if not seg:
                continue
            if len(seg) <= 4:
                # 短片段直接作为词
                words.append(seg)
            else:
                # 长片段：生成 bigram
                for i in range(len(seg) - 1):
                    words.append(seg[i:i + 2])

        return words
