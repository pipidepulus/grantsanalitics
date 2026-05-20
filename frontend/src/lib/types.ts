export interface User {
  id: string;
  name: string;
  email: string;
  organization: string | null;
  sector: string | null;
  territory: string | null;
  preferences: Record<string, unknown> | null;
  created_at: string;
}

export interface Project {
  id: string;
  user_id: string;
  title: string;
  status: string;
  cyrano_score: number | null;
  language: string;
  json_data: Record<string, unknown> | null;
  problem_definition: string | null;
  problem_tree: Record<string, unknown> | null;
  objectives_tree: Record<string, unknown> | null;
  value_chain: Record<string, unknown> | null;
  timeline: Record<string, unknown> | null;
  budget: Record<string, unknown> | null;
  call_spec_id: string | null;
  created_at: string;
  updated_at: string;
}

export interface ProjectListItem {
  id: string;
  title: string;
  status: string;
  cyrano_score: number | null;
  language: string;
  created_at: string;
}

export interface ChatMessage {
  id: string;
  role: "user" | "assistant" | "system";
  content: string;
  tool_calls: Record<string, unknown> | null;
  created_at: string;
}

export interface Conversation {
  id: string;
  title: string;
  project_id: string | null;
  created_at: string;
  updated_at: string;
  message_count?: number;
  messages?: ChatMessage[];
}

export interface ChatResponse {
  conversation_id: string;
  message: ChatMessage;
  project_update: { cyrano_score: number; status: string } | null;
  cyrano_score: number | null;
}

export interface CallSpec {
  id: string;
  title: string;
  source_url: string | null;
  extracted_requirements: Record<string, unknown> | null;
  eligibility_criteria: string | null;
  max_amount: string | null;
  counterpart_required: string | null;
  deadline: string | null;
  mandatory_sections: Record<string, unknown> | null;
  created_at: string;
}

export interface CyranoEvaluation {
  id: string;
  score: number;
  version: number;
  verdict: string | null;
  sections: {
    problem_definition?: number;
    problem_tree?: number;
    objectives?: number;
    value_chain?: number;
    timeline?: number;
    budget?: number;
  } | null;
  feedback: {
    gaps: string[];
    recommendations: string[];
  } | null;
  created_at: string;
}

export interface GeneratedDoc {
  id: string;
  project_id: string;
  filename: string;
  version_number: number;
  created_at: string;
}

export interface UploadedDocument {
  id: string;
  project_id: string;
  user_id: string;
  filename: string;
  original_filename: string;
  file_size: number;
  content_type: string;
  vector_store_file_id: string | null;
  indexing_status: string;
  created_at: string;
}

export interface ProjectDocuments {
  uploaded: {
    id: string;
    filename: string;
    file_size: number;
    content_type: string;
    type: "uploaded";
    indexing_status: string;
    created_at: string;
  }[];
  generated: {
    id: string;
    filename: string;
    version_number: number;
    type: "generated";
    created_at: string;
  }[];
}

export interface CyranoEvaluation {
  id: string;
  project_id: string;
  score: number;
  sections: Record<string, number> | null;
  feedback: { gaps: string[]; recommendations: string[] } | null;
  verdict: string | null;
  version: number;
  created_at: string;
}
