/**
 * API service using axios for backend communication.
 */
import axios from 'axios';
import { filenameFromContentDisposition } from '../utils/downloadFile';
import type {
    Feed,
    ArticleDetail,
    ArticleListResponse,
    ArticleFilters,
    ArticleCounts,
    ReprocessRequest,
    ReprocessResponse,
    ReprocessStatus,
    Summary,
    Topic,
    UserSettings,
    CostStats,
    SystemPrompt,
    LockedPrompt,
    AppUser,
    LoginResponse,
    BulletinCategory,
    BulletinGenerateRequest,
    BulletinPreviewCountResponse,
    GeneratedBulletin,
    PlaygroundSettings,
    PlaygroundRunRequest,
    PlaygroundRunResult,
} from '../types';

const API_BASE_URL = '/api';

const api = axios.create({
    baseURL: API_BASE_URL,
    timeout: 20000,
    headers: {
        'Content-Type': 'application/json',
    },
});

// Attach JWT token to every request
api.interceptors.request.use((config) => {
    const token = localStorage.getItem('auth_token');
    if (token) {
        config.headers.Authorization = `Bearer ${token}`;
    }
    return config;
});

// Handle 401 responses: clear session and dispatch logout event
api.interceptors.response.use(
    (response) => response,
    (error) => {
        if (error.response?.status === 401) {
            localStorage.removeItem('auth_token');
            localStorage.removeItem('auth_user');
            window.dispatchEvent(new Event('auth:logout'));
        }
        return Promise.reject(error);
    }
);

// Auth endpoints
export const authApi = {
    login: async (email: string, password: string): Promise<LoginResponse> => {
        const response = await api.post('/auth/login', { email, password });
        return response.data;
    },

    me: async (): Promise<AppUser> => {
        const response = await api.get('/auth/me');
        return response.data;
    },

    listUsers: async (): Promise<AppUser[]> => {
        const response = await api.get('/auth/users');
        return response.data;
    },

    createUser: async (data: { email: string; password: string; role: string }): Promise<AppUser> => {
        const response = await api.post('/auth/users', data);
        return response.data;
    },

    deleteUser: async (userId: number): Promise<void> => {
        await api.delete(`/auth/users/${userId}`);
    },
};

// Feed endpoints
export const feedsApi = {
    list: async (activeOnly: boolean = true): Promise<Feed[]> => {
        const response = await api.get('/feeds/', { params: { active_only: activeOnly } });
        return response.data;
    },

    get: async (feedId: number): Promise<Feed> => {
        const response = await api.get(`/feeds/${feedId}`);
        return response.data;
    },

    create: async (url: string, title?: string, description?: string): Promise<Feed> => {
        const response = await api.post('/feeds/', { url, title, description });
        return response.data;
    },

    test: async (url: string): Promise<{ status: string }> => {
        const response = await api.post('/feeds/test', { url });
        return response.data;
    },

    update: async (
        feedId: number,
        data: { url?: string; title?: string; description?: string; is_active?: boolean }
    ): Promise<Feed> => {
        const response = await api.put(`/feeds/${feedId}`, data);
        return response.data;
    },

    refresh: async (feedId: number): Promise<{ status: string; feed_id: number }> => {
        const response = await api.post(`/feeds/${feedId}/refresh`);
        return response.data;
    },

    getRefreshStatus: async (feedId: number): Promise<{
        status: 'idle' | 'running' | 'done' | 'error';
        new_articles?: number;
        processed?: number;
        errors?: number;
        message?: string;
    }> => {
        const response = await api.get(`/feeds/${feedId}/refresh-status`);
        return response.data;
    },

    delete: async (feedId: number): Promise<{ status: string; feed_id: number }> => {
        const response = await api.delete(`/feeds/${feedId}`);
        return response.data;
    },
};

// Article endpoints
export const articlesApi = {
    delete: async (articleId: number): Promise<void> => {
        await api.delete(`/articles/${articleId}`);
    },
    markRead: async (articleId: number): Promise<void> => {
        await api.patch(`/articles/${articleId}/read`);
    },
    setStarred: async (articleId: number, starred: boolean): Promise<void> => {
        await api.patch(`/articles/${articleId}/star`, { starred });
    },
    unstarAll: async (): Promise<{ unstarred_count: number }> => {
        const response = await api.post('/articles/unstar-all');
        return response.data;
    },
    markBulkRead: async (articleIds?: number[], filters?: ArticleFilters): Promise<{ marked_count: number }> => {
        const body = articleIds ? { article_ids: articleIds } : { mark_all: true, ...filters };
        const response = await api.post('/articles/mark-read-bulk', body);
        return response.data;
    },
    reprocess: async (payload: ReprocessRequest): Promise<ReprocessResponse> => {
        const response = await api.post('/articles/reprocess', payload);
        return response.data;
    },
    getReprocessStatus: async (): Promise<ReprocessStatus> => {
        const response = await api.get('/articles/reprocess-status');
        return response.data;
    },
    list: async (filters: ArticleFilters = {}): Promise<ArticleListResponse> => {
        const response = await api.get('/articles/', { params: filters });
        return response.data;
    },

    get: async (articleId: number): Promise<ArticleDetail> => {
        const response = await api.get(`/articles/${articleId}`);
        return response.data;
    },

    getCounts: async (): Promise<ArticleCounts> => {
        const response = await api.get('/articles/counts');
        return response.data;
    },

    getByTopic: async (
        topicName: string,
        skip: number = 0,
        limit: number = 50
    ): Promise<ArticleListResponse> => {
        const response = await api.get(`/articles/topic/${topicName}`, {
            params: { skip, limit },
        });
        return response.data;
    },

    getIdsByTopic: async (topicId: number): Promise<number[]> => {
        const response = await api.get(`/articles/topic/${topicId}/ids`);
        return response.data.article_ids;
    },

    deleteAllByPriority: async (priority: string, feedIds?: number[]): Promise<{ deleted_count: number }> => {
        const response = await api.post(`/articles/priority/${priority}/delete-all`, null, {
            params: feedIds && feedIds.length > 0 ? { feed_ids: feedIds.join(',') } : {},
        });
        return response.data;
    },

    archiveAllByPriority: async (priority: string, feedIds?: number[]): Promise<{ archived_count: number }> => {
        const response = await api.post(`/articles/priority/${priority}/archive-all`, null, {
            params: feedIds && feedIds.length > 0 ? { feed_ids: feedIds.join(',') } : {},
        });
        return response.data;
    },

    deleteAllUnimportant: async (feedIds?: number[]): Promise<{ deleted_count: number }> => {
        const response = await api.post('/articles/unimportant/delete-all', null, {
            params: feedIds && feedIds.length > 0 ? { feed_ids: feedIds.join(',') } : {},
        });
        return response.data;
    },

    archiveAllUnimportant: async (feedIds?: number[]): Promise<{ archived_count: number }> => {
        const response = await api.post('/articles/unimportant/archive-all', null, {
            params: feedIds && feedIds.length > 0 ? { feed_ids: feedIds.join(',') } : {},
        });
        return response.data;
    },
};

// Summary endpoints
export const summariesApi = {
    getByArticle: async (articleId: number, summaryType?: string): Promise<Summary[]> => {
        const response = await api.get(`/articles/${articleId}/summaries`, {
            params: summaryType ? { summary_type: summaryType } : {},
        });
        return response.data;
    },

    getByType: async (
        articleId: number,
        summaryType: 'brief' | 'standard' | 'detailed'
    ): Promise<Summary> => {
        const response = await api.get(`/articles/${articleId}/summary/${summaryType}`);
        return response.data;
    },
};

// Topic endpoints
export const topicsApi = {
    list: async (feedId?: number): Promise<Topic[]> => {
        const response = await api.get('/topics/', { params: feedId != null ? { feed_id: feedId } : {} });
        return response.data;
    },

    create: async (name: string, description?: string, color?: string): Promise<Topic> => {
        const response = await api.post('/topics/', { name, description, color });
        return response.data;
    },

    update: async (topicId: number, name?: string, description?: string, color?: string): Promise<Topic> => {
        const response = await api.put(`/topics/${topicId}`, { name, description, color });
        return response.data;
    },

    delete: async (topicId: number): Promise<{ status: string; message: string }> => {
        const response = await api.delete(`/topics/${topicId}`);
        return response.data;
    },
};

// Settings endpoints
export const settingsApi = {
    get: async (): Promise<UserSettings> => {
        const response = await api.get('/settings/');
        return response.data;
    },

    update: async (settings: UserSettings): Promise<UserSettings> => {
        const response = await api.put('/settings/', settings);
        return response.data;
    },
};

// Stats endpoints
export const statsApi = {
    getCosts: async (): Promise<CostStats> => {
        const response = await api.get('/stats/costs');
        return response.data;
    },
};

// App info
export const appApi = {
    getInfo: async (): Promise<{ app: string; version: string; status: string }> => {
        const response = await api.get('/info');
        return response.data;
    },
};

// System Prompts endpoints
export const promptsApi = {
    list: async (): Promise<SystemPrompt[]> => {
        const response = await api.get('/prompts/');
        return response.data;
    },

    get: async (promptType: string): Promise<SystemPrompt> => {
        const response = await api.get(`/prompts/${promptType}`);
        return response.data;
    },

    getLocked: async (promptType: string): Promise<LockedPrompt> => {
        const response = await api.get(`/prompts/${promptType}/locked`);
        return response.data;
    },

    create: async (promptType: string, promptText: string, isActive: boolean = true): Promise<SystemPrompt> => {
        const response = await api.post('/prompts/', {
            prompt_type: promptType,
            prompt_text: promptText,
            is_active: isActive
        });
        return response.data;
    },

    update: async (promptType: string, promptText?: string, isActive?: boolean): Promise<SystemPrompt> => {
        const response = await api.put(`/prompts/${promptType}`, {
            prompt_text: promptText,
            is_active: isActive
        });
        return response.data;
    },
};

// Bulletin (Word report) endpoints
export const bulletinApi = {
    listCategories: async (): Promise<BulletinCategory[]> => {
        const response = await api.get('/bulletin/categories');
        return response.data;
    },

    createCategory: async (name: string): Promise<BulletinCategory> => {
        const response = await api.post('/bulletin/categories', { name });
        return response.data;
    },

    updateCategory: async (categoryId: number, name: string): Promise<BulletinCategory> => {
        const response = await api.put(`/bulletin/categories/${categoryId}`, { name });
        return response.data;
    },

    deleteCategory: async (categoryId: number): Promise<void> => {
        await api.delete(`/bulletin/categories/${categoryId}`);
    },

    reorderCategories: async (orderedIds: number[]): Promise<BulletinCategory[]> => {
        const response = await api.put('/bulletin/categories/reorder', { ordered_ids: orderedIds });
        return response.data;
    },

    generate: async (payload: BulletinGenerateRequest): Promise<{ blob: Blob; filename: string }> => {
        const response = await api.post('/bulletin/generate', payload, { responseType: 'blob' });
        return {
            blob: response.data,
            filename: filenameFromContentDisposition(response.headers['content-disposition'], 'bulten.docx'),
        };
    },

    previewCount: async (params: BulletinGenerateRequest): Promise<BulletinPreviewCountResponse> => {
        const response = await api.get('/bulletin/preview-count', {
            params: {
                published_from: params.published_from,
                published_to: params.published_to,
                priorities: params.priorities && params.priorities.length > 0 ? params.priorities.join(',') : undefined,
                include_favorites: params.include_favorites,
            },
        });
        return response.data;
    },

    listGenerated: async (): Promise<GeneratedBulletin[]> => {
        const response = await api.get('/bulletin/generated');
        return response.data;
    },

    downloadGenerated: async (id: number): Promise<Blob> => {
        const response = await api.get(`/bulletin/generated/${id}/download`, { responseType: 'blob' });
        return response.data;
    },

    deleteGenerated: async (id: number): Promise<void> => {
        await api.delete(`/bulletin/generated/${id}`);
    },
};

export const playgroundApi = {
    getSettings: async (): Promise<PlaygroundSettings> => {
        const response = await api.get('/playground/settings');
        return response.data;
    },

    // Runs up to four sequential LLM calls, so it needs far more than the default 20s timeout.
    run: async (request: PlaygroundRunRequest): Promise<PlaygroundRunResult> => {
        const response = await api.post('/playground/run', request, { timeout: 120000 });
        return response.data;
    },
};

export default api;
