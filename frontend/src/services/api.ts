/**
 * API service using axios for backend communication.
 */
import axios from 'axios';
import type {
    Feed,
    ArticleDetail,
    ArticleListResponse,
    ArticleFilters,
    ArticleCounts,
    Summary,
    Topic,
    UserSettings,
    CostStats,
    SystemPrompt,
    AppUser,
    LoginResponse,
} from '../types';

const API_BASE_URL = '/api';

const api = axios.create({
    baseURL: API_BASE_URL,
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

    checkNew: async (feedId: number): Promise<{
        feed_id: number;
        total_articles: number;
        new_articles: number;
        existing_articles: number;
        new_articles_list?: Array<{ title: string; url: string; published_at?: string }>;
    }> => {
        const response = await api.get(`/feeds/${feedId}/check-new`);
        return response.data;
    },

    refresh: async (feedId: number): Promise<{ status: string; feed_id: number }> => {
        const response = await api.post(`/feeds/${feedId}/refresh`);
        return response.data;
    },

    addArticles: async (feedId: number, articles: Array<{ title: string; url: string; published_at?: string }>): Promise<{ feed_id: number; created: number; skipped: number; created_list?: string[] }> => {
        const response = await api.post(`/feeds/${feedId}/add-articles`, { articles });
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
        const response = await axios.get('/');
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

export default api;
