/* ── 课件 ──────────────────────────────────────── */

export interface Course {
  id: string;
  name: string;
  term: string;
  description: string;
  courseware_count: number;
  homework_count: number;
  folder_count: number;
  session_count: number;
  created_at: string;
  updated_at: string;
}

/** 课件状态 */
export type CoursewareStatus =
  | "processing"
  | "partial"
  | "completed"
  | "failed";

/** 课件条目（与后端 CoursewareResponse 对应） */
export interface Courseware {
  id: string;
  course_id: string;
  title: string;
  file_type: string;
  file_size: number;
  status: CoursewareStatus;
  parse_status: string;
  knowledge_status: string;
  embedding_status: string;
  linking_status: string;
  failed_stage: string | null;
  retry_count: number;
  error_message: string | null;
  page_count: number | null;
  use_vision?: boolean;
  folder_id: string | null;
  created_at: string; // ISO-8601
  updated_at: string; // ISO-8601
}

/* ── 知识点 ────────────────────────────────────── */

/** 知识点条目（与后端 KnowledgePointResponse 对应） */
export interface KnowledgePoint {
  id: string;
  courseware_id: string;
  title: string;
  content: string;
  page_number: number | null;
  order_index: number;
  revision: number;
  indexing_status: "processing" | "completed" | "failed";
  indexing_error: string | null;
  examples: Example[];
  created_at: string;
  updated_at: string;
}

/* ── 例题 ──────────────────────────────────────── */

/** 例题条目（与后端 ExampleResponse 对应） */
export interface Example {
  id: string;
  courseware_id: string;
  knowledge_point_id: string | null;
  question: string;
  answer: string;
  explanation: string | null;
  created_at: string;
}

/* ── 作业 ──────────────────────────────────────── */

/** 作业状态 */
export type HomeworkStatus = "pending" | "ready" | "processing" | "partial" | "completed" | "failed";

/** 作业条目（与后端 HomeworkResponse 对应） */
export interface Homework {
  id: string;
  course_id: string;
  title: string;
  file_type: string;
  file_size: number;
  status: HomeworkStatus;
  error_message: string | null;
  folder_id: string | null;
  created_at: string;
  updated_at: string;
}

/** 作业解答 */
export interface Solution {
  id: string;
  question_number: number;
  question_text: string;
  answer_text: string | null;
  thinking_process: string | null;
  created_at: string;
  knowledge_point_links: SolutionKnowledgePointRef[];
}

/** 解答关联的知识点引用 */
export interface SolutionKnowledgePointRef {
  id: string;
  knowledge_point_id: string;
  knowledge_point_title: string;
  relevance_score: number;
  match_method: string;
}

/** 作业详情（含解答列表） */
export interface HomeworkDetail extends Homework {
  solutions: Solution[];
}

/* ── 文件夹 ────────────────────────────────────── */

/** 文件夹 */
export interface Folder {
  id: string;
  course_id: string;
  name: string;
  category: "courseware" | "homework";
  courseware_count: number;
  homework_count: number;
  created_at: string;
  updated_at: string;
}

/* ── 聊天 ──────────────────────────────────────── */

/** 聊天会话 */
export interface ChatSession {
  id: string;
  title: string;
  courseware_id: string | null;
  knowledge_point_id: string | null;
  created_at: string;
  updated_at: string;
}

/** 聊天消息 */
export interface ChatMessage {
  id: string;
  session_id: string;
  role: "user" | "assistant" | "system";
  content: string;
  created_at: string;
}

/* ── 通用分页 ──────────────────────────────────── */

/** 分页响应包装 */
export interface PaginatedResponse<T> {
  items: T[];
  total: number;
  page: number;
  size: number;
  pages: number;
}

/** 通用列表响应 */
export interface ListResponse<T> {
  items: T[];
  total: number;
}

/* ── AI 生成题目 ────────────────────────────────── */

/** 题目类型 */
export type QuestionType = '选择题' | '填空题' | '计算题' | '证明题';

/** AI 生成的练习题 */
export interface GeneratedQuestion {
  id: string;
  courseware_id: string;
  knowledge_point_id: string;
  question_type: QuestionType;
  question_text: string;
  options: string[] | null;
  answer_text: string;
  explanation: string | null;
  source_style: 'from_example' | 'ai_generated';
  difficulty: string;
  knowledge_points: { id: string; title: string }[];
  courseware_title?: string;
  created_at: string;
}

/** 题目分页列表响应 */
export interface QuestionListResponse {
  items: GeneratedQuestion[];
  total: number;
  page: number;
  size: number;
  pages: number;
}

/* ── 学习进度 ──────────────────────────────────── */

/** 进度状态 */
export type ProgressStatus = 'not_started' | 'in_progress' | 'mastered' | 'struggling';

/** 学习进度记录 */
export interface StudyProgress {
  knowledge_point_id: string;
  status: ProgressStatus;
  manual_status: ProgressStatus | null;
  quiz_correct_count: number;
  quiz_total_count: number;
  correct_streak: number;
  answered_question_count: number;
  last_reviewed_at: string | null;
  updated_at: string;
}

/** 课件进度汇总 */
export interface CoursewareProgressSummary {
  items: StudyProgress[];
  mastered_count: number;
  in_progress_count: number;
  not_started_count: number;
  struggling_count: number;
  total_count: number;
}

/** 全局进度汇总 */
export interface OverallProgress {
  total_knowledge_points: number;
  mastered_count: number;
  in_progress_count: number;
  not_started_count: number;
  struggling_count: number;
  coursewares: {
    courseware_id: string;
    title: string;
    mastered: number;
    total: number;
    in_progress: number;
    not_started: number;
    struggling: number;
  }[];
}
