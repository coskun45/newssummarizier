/**
 * TypeScript type definitions for the application.
 */

export interface Feed {
    id: number;
    url: string;
    title: string | null;
    description: string | null;
    last_fetched: string | null;
    is_active: boolean;
    created_at: string;
}

export interface Topic {
    id: number;
    name: string;
    description: string | null;
    color: string | null;
    confidence?: number;
    article_count?: number;
    unread_count?: number;
}

export interface Article {
    id: number;
    url: string;
    title: string;
    author: string | null;
    published_at: string | null;
    fetched_at: string;
    status: string;
    importance: string | null;
    priority: string | null;
    image_url: string | null;
    topics: Topic[];
    has_summaries: boolean;
    is_read: boolean;
    is_starred: boolean;
}

export interface ArticleDetail extends Article {
    raw_content: string | null;
    cleaned_content: string | null;
}

export interface Summary {
    id: number;
    article_id: number;
    summary_text: string;
    summary_type: "brief" | "standard" | "detailed";
    model_used: string;
    tokens_used: number;
    cost: number;
    created_at: string;
}

export interface ArticleListResponse {
    articles: Article[];
    total: number;
    skip: number;
    limit: number;
}

export interface DateFilterState {
    preset: 'today' | 'week' | 'custom' | null;
    customFrom: string;
    customTo: string;
}

export interface ArticleFilters {
    skip?: number;
    limit?: number;
    topic_ids?: string;
    search?: string;
    status?: string;
    feed_id?: number;
    feed_ids?: string;
    priority?: string;
    published_from?: string;
    published_to?: string;
    fetched_from?: string;
    fetched_to?: string;
    is_read?: boolean;
    is_starred?: boolean;
    is_error?: boolean;
}

export interface UserSettings {
    enabled_topics: string;
    enabled_summary_types: string;
    feed_refresh_interval: number;
}

export interface CostStats {
    daily_cost: number;
    monthly_cost: number;
    daily_limit: number;
    monthly_limit: number;
}

export interface SystemPrompt {
    id: number;
    prompt_type: string;
    prompt_text: string;
    is_active: boolean;
    created_at: string;
    updated_at: string;
}

export interface ArticleCounts {
    by_priority: Record<string, number>;
    by_feed: Record<string, number>;
    unimportant_count: number;
    unread_count: number;
    read_count: number;
    starred_count: number;
    error_count: number;
}

export interface ReprocessRequest {
    article_ids?: number[];
    all_errors?: boolean;
    feed_ids?: number[];
}

export interface ReprocessResponse {
    queued: number;
    article_ids: number[];
}

export interface ReprocessStatus {
    status: 'idle' | 'running' | 'done';
    total: number;
    done: number;
    failed: number;
}

export interface AuthUser {
    id: number;
    email: string;
    role: 'admin' | 'user';
}

export interface AppUser {
    id: number;
    email: string;
    role: string;
    is_active: boolean;
    created_at: string;
}

export interface LoginResponse {
    access_token: string;
    token_type: string;
    user: AppUser;
}

export interface BulletinCategory {
    id: number;
    name: string;
    display_order: number;
}

export interface BulletinGenerateRequest {
    published_from?: string;
    published_to?: string;
    priorities?: string[];
    include_favorites?: boolean;
}

export interface BulletinPreviewCountResponse {
    count: number;
}

export interface GeneratedBulletin {
    id: number;
    filename: string;
    published_from: string | null;
    published_to: string | null;
    priorities: string[] | null;
    include_favorites: boolean;
    article_count: number;
    generated_at: string;
}

// Playground (dry-run of the pipeline on a single stored article)
export type PlaygroundStage = 'classification' | 'summarization';
export type PlaygroundSummaryType = 'brief' | 'standard' | 'detailed';

export interface PlaygroundPromptInfo {
    text: string;
    source: 'db' | 'default';
}

export interface PlaygroundSummaryTypeInfo {
    type: PlaygroundSummaryType;
    model: string;
    max_tokens: number;
    default_instructions: string;
    enabled: boolean;
}

export interface PlaygroundSettings {
    classification_model: string;
    classification_prompt: PlaygroundPromptInfo;
    summarization_prompt: PlaygroundPromptInfo;
    summary_types: PlaygroundSummaryTypeInfo[];
    topics: { name: string; description: string | null }[];
}

export interface PlaygroundRunRequest {
    article_id: number;
    stages: PlaygroundStage[];
    classification_prompt?: string;
    summarization_prompt?: string;
    summary_instructions?: Partial<Record<PlaygroundSummaryType, string>>;
    summary_types?: PlaygroundSummaryType[];
    force_summarize?: boolean;
}

export interface PlaygroundAttempt {
    attempt: number;
    user_prompt: string;
    raw_response: string | null;
    error: string | null;
    input_tokens: number;
    output_tokens: number;
    finish_reason: string | null;
    latency_ms: number;
}

export interface PlaygroundStageCall {
    model: string;
    system_prompt: string;
    prompt_source: 'override' | 'db' | 'default';
    temperature: number;
    max_completion_tokens: number;
    attempts: PlaygroundAttempt[];
    error: string | null;
    input_tokens: number;
    output_tokens: number;
    cost: number;
    latency_ms: number;
}

export interface PlaygroundTopicResult {
    name: string;
    confidence: number | null;
    known: boolean;
}

export interface PlaygroundClassificationResult extends PlaygroundStageCall {
    importance: string | null;
    priority: string | null;
    topics: PlaygroundTopicResult[];
    pipeline_outcome: 'continue' | 'filtered' | 'failed';
}

export interface PlaygroundSummaryResult extends PlaygroundStageCall {
    summary_type: PlaygroundSummaryType;
    instructions: string;
    summary_text: string | null;
    tokens_used: number;
}

export interface PlaygroundRunResult {
    article: { id: number; title: string; url: string };
    content_used: { source: 'cleaned' | 'raw' | 'none'; chars: number; used_chars: number; truncated: boolean };
    classification: PlaygroundClassificationResult | null;
    summaries: PlaygroundSummaryResult[];
    skipped_reason: 'unimportant' | 'classification_failed' | null;
    total_cost: number;
}
