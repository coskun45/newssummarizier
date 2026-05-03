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
    topics: Topic[];
    has_summaries: boolean;
    is_read: boolean;
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
