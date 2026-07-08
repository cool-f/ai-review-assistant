/**
 * ReactMarkdown 通用插件配置
 * — 智能 LaTeX 检测：只有真正像公式的 $...$ 才会渲染
 * — 非公式的 $ 自动转义，避免误解析（如 $100、$变量 不受影响）
 * — 安全过滤 HTML，同时保留 KaTeX 生成的 class 和 style
 */
import remarkMath from "remark-math";
import rehypeKatex from "rehype-katex";
import rehypeSanitize from "rehype-sanitize";
import { defaultSchema } from "hast-util-sanitize";
import type { Schema } from "hast-util-sanitize";
import type { PluggableList } from "unified";
import type { KatexOptions } from "katex";
import type { Root } from "mdast";
import { visit } from "unist-util-visit";

// ── 判断 $...$ 内容是否像数学公式 ──────────────────

const MATH_INDICATOR = /[\\^_{}+*/=<>|~]|\\\\|\\frac|\\sum|\\int|\\alpha|\\beta|\\gamma|\\delta|\\epsilon|\\theta|\\pi|\\sigma|\\omega|\\sqrt|\\begin|\\end/;
const PURE_CURRENCY = /^\d[\d,.]*\s*$/;   // $100, $1,234.56
const PURE_WORD = /^[a-zA-Z]\w{0,20}\s*$/; // $variable, $name

function looksLikeMath(content: string): boolean {
  const trimmed = content.trim();
  if (!trimmed) return false;
  // 纯数字金额 → 不是公式
  if (PURE_CURRENCY.test(trimmed)) return false;
  // 纯字母变量名 → 不是公式
  if (PURE_WORD.test(trimmed)) return false;
  // 不含任何数学特征 → 不是公式
  if (!MATH_INDICATOR.test(trimmed)) return false;
  return true;
}

// ── 自定义 remark 插件：过滤非公式的 $...$ ────────

/**
 * 在 remark-math 之前运行。
 * 遍历所有 text 节点，找到 $...$ 配对：
 * - 像公式的 → 保留，交给 remark-math
 * - 不像公式的 → 用 \$ 转义（markdown 转义符）
 */
function smartDollarMath() {
  return (tree: Root) => {
    visit(tree, "text", (node, index, parent) => {
      if (!parent || index === undefined || !("children" in parent)) return;

      const text = node.value as string;
      // 快速路径：没有 $ 直接跳过
      if (!text.includes("$")) return;

      // 逐个字符扫描找 $...$ 配对
      let i = 0;
      let dollarOpen = -1;

      while (i < text.length) {
        if (text[i] === "$" && (i === 0 || text[i - 1] !== "\\")) {
          if (dollarOpen === -1) {
            dollarOpen = i;
          } else {
            // 找到了闭合 $
            const before = text.slice(dollarOpen + 1, i);
            const isMath = looksLikeMath(before);

            if (isMath) {
              // 留下 $...$ 原文，让 remark-math 处理
              // 不需要修改
              dollarOpen = -1;
              i++;
              continue;
            } else {
              // 转义 $：替换为 HTML 实体 $，remark-math 不识别实体
              const fullMatch = text.slice(dollarOpen, i + 1);
              const escaped = fullMatch.replace(/\$/g, "&#36;");
              // 构建替换后的文本
              const before = text.slice(0, dollarOpen);
              const after = text.slice(i + 1);
              node.value = before + escaped + after;
              // 重置扫描位置
              i = before.length + escaped.length;
              dollarOpen = -1;
            }
          }
        }
        i++;
      }

      // 如果只有一个未闭合的 $，把它也转义
      if (dollarOpen !== -1) {
        const before = text.slice(0, dollarOpen);
        const after = text.slice(dollarOpen + 1);
        node.value = before + "&#36;" + after;
      }
    });
  };
}

// ── KaTeX 配置 ────────────────────────────────────

const katexOptions: KatexOptions = {
  throwOnError: false,
  strict: false,
  output: "html",
  trust: true,
};

// ── 扩展 sanitize schema ──────────────────────────

const katexSchema: Schema = {
  ...defaultSchema,
  attributes: {
    ...defaultSchema.attributes,
    "*": [
      ...(defaultSchema.attributes?.["*"] ?? []),
      "className", "style", "ariaHidden", "aria-hidden",
    ],
    span: [
      ...(defaultSchema.attributes?.span ?? []),
      "className", "style", "ariaHidden", "aria-hidden",
    ],
    math: [
      ...(defaultSchema.attributes?.math ?? []),
      "className", "style", "ariaHidden", "aria-hidden",
    ],
    semantics: ["className"],
    annotation: ["encoding"],
    svg: [
      ...(defaultSchema.attributes?.svg ?? []),
      "className", "style", "width", "height", "viewBox", "preserveAspectRatio",
    ],
    path: [
      ...(defaultSchema.attributes?.path ?? []),
      "d", "fill", "stroke", "strokeWidth", "strokeLinecap", "strokeLinejoin",
      "strokeMiterlimit", "strokeDasharray", "strokeDashoffset",
      "strokeOpacity", "fillRule", "fillOpacity",
    ],
    img: [
      ...(defaultSchema.attributes?.img ?? []),
      "src", "alt", "className", "style", "width", "height",
    ],
  },
  tagNames: [
    ...(defaultSchema.tagNames ?? []),
    "svg", "path", "math", "semantics", "annotation",
    "mrow", "msup", "mover", "munder", "mfrac", "msqrt", "mroot",
    "mtable", "mtr", "mtd", "mstyle", "mspace", "mo", "mi", "mn", "mtext",
  ],
};

const sanitizeWithKaTeX: [typeof rehypeSanitize, Schema] = [rehypeSanitize, katexSchema];

// ── 导出 ──────────────────────────────────────────

// smartDollarMath 必须在 remarkMath 之前运行
export const remarkPlugins: PluggableList = [
  smartDollarMath,
  remarkMath,
];
export const rehypePlugins: PluggableList = [
  [rehypeKatex, katexOptions],
  sanitizeWithKaTeX,
];
