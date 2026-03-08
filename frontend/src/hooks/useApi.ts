/**
 * React Query hooks for data fetching and caching.
 */
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query';
import { articlesApi, summariesApi, topicsApi, settingsApi, statsApi, feedsApi, authApi } from '../services/api';
import type { ArticleFilters, UserSettings } from '../types';

// Articles hooks
export const useArticleCounts = () => {
    return useQuery({
        queryKey: ['articleCounts'],
        queryFn: () => articlesApi.getCounts(),
        staleTime: 30000,
    });
};

export const useArticles = (filters: ArticleFilters = {}) => {
    return useQuery({
        queryKey: ['articles', filters],
        queryFn: () => articlesApi.list(filters),
        staleTime: 30000, // 30 seconds
    });
};

export const useArticle = (articleId: number | null) => {
    return useQuery({
        queryKey: ['article', articleId],
        queryFn: () => articlesApi.get(articleId!),
        enabled: articleId !== null,
    });
};

export const useDeleteArticle = () => {
    const queryClient = useQueryClient();
    return useMutation({
        mutationFn: (articleId: number) => articlesApi.delete(articleId),
        onSuccess: () => {
            queryClient.invalidateQueries({ queryKey: ['articles'] });
        },
    });
};

// Summary hooks
export const useSummary = (articleId: number | null, summaryType: 'brief' | 'standard' | 'detailed') => {
    return useQuery({
        queryKey: ['summary', articleId, summaryType],
        queryFn: () => summariesApi.getByType(articleId!, summaryType),
        enabled: articleId !== null,
        staleTime: Infinity, // Summaries don't change
    });
};

export const useSummaries = (articleId: number | null) => {
    return useQuery({
        queryKey: ['summaries', articleId],
        queryFn: () => summariesApi.getByArticle(articleId!),
        enabled: articleId !== null,
        staleTime: Infinity,
    });
};

// Topics hooks
export const useTopics = (feedId?: number | null) => {
    return useQuery({
        queryKey: ['topics', feedId ?? null],
        queryFn: () => topicsApi.list(feedId ?? undefined),
        staleTime: 30000,
    });
};

export const useCreateTopic = () => {
    const queryClient = useQueryClient();

    return useMutation({
        mutationFn: ({ name, description, color }: { name: string; description?: string; color?: string }) =>
            topicsApi.create(name, description, color),
        onSuccess: () => {
            queryClient.invalidateQueries({ queryKey: ['topics'] });
        },
    });
};

export const useUpdateTopic = () => {
    const queryClient = useQueryClient();

    return useMutation({
        mutationFn: ({ topicId, name, description, color }: { topicId: number; name?: string; description?: string; color?: string }) =>
            topicsApi.update(topicId, name, description, color),
        onSuccess: () => {
            queryClient.invalidateQueries({ queryKey: ['topics'] });
        },
    });
};

export const useDeleteTopic = () => {
    const queryClient = useQueryClient();

    return useMutation({
        mutationFn: (topicId: number) => topicsApi.delete(topicId),
        onSuccess: () => {
            queryClient.invalidateQueries({ queryKey: ['topics'] });
        },
    });
};

// Settings hooks
export const useSettings = () => {
    return useQuery({
        queryKey: ['settings'],
        queryFn: settingsApi.get,
    });
};

export const useUpdateSettings = () => {
    const queryClient = useQueryClient();

    return useMutation({
        mutationFn: (settings: UserSettings) => settingsApi.update(settings),
        onSuccess: () => {
            queryClient.invalidateQueries({ queryKey: ['settings'] });
            queryClient.invalidateQueries({ queryKey: ['topics'] });
        },
    });
};

// Stats hooks
export const useCostStats = () => {
    return useQuery({
        queryKey: ['costStats'],
        queryFn: statsApi.getCosts,
        refetchInterval: 60000, // Refetch every minute
    });
};

// Feed hooks
export const useFeeds = () => {
    return useQuery({
        queryKey: ['feeds'],
        queryFn: () => feedsApi.list(),
    });
};

export const useCreateFeed = () => {
    const queryClient = useQueryClient();
    return useMutation({
        mutationFn: ({ url, title }: { url: string; title?: string }) =>
            feedsApi.create(url, title),
        onSuccess: () => {
            queryClient.invalidateQueries({ queryKey: ['feeds'] });
        },
    });
};

export const useDeleteFeed = () => {
    const queryClient = useQueryClient();
    return useMutation({
        mutationFn: (feedId: number) => feedsApi.delete(feedId),
        onSuccess: () => {
            queryClient.invalidateQueries({ queryKey: ['feeds'] });
            queryClient.invalidateQueries({ queryKey: ['articles'] });
        },
    });
};

export const useCheckNewArticles = (feedId: number | null) => {
    return useQuery({
        queryKey: ['checkNewArticles', feedId],
        queryFn: () => feedsApi.checkNew(feedId!),
        enabled: false, // Manual trigger only
        staleTime: 0, // Always fresh
    });
};

export const useRefreshFeed = () => {
    const queryClient = useQueryClient();

    return useMutation({
        mutationFn: (feedId: number) => feedsApi.refresh(feedId),
        onSuccess: () => {
            // Invalidate articles to refetch after feed refresh
            setTimeout(() => {
                queryClient.invalidateQueries({ queryKey: ['articles'] });
            }, 5000); // Wait 5 seconds for processing
        },
    });
};


export const useAddArticlesToFeed = () => {
    const queryClient = useQueryClient();

    return useMutation({
        mutationFn: ({ feedId, articles }: { feedId: number; articles: Array<{ title: string; url: string; published_at?: string }> }) =>
            feedsApi.addArticles(feedId, articles),
        onSuccess: () => {
            queryClient.invalidateQueries({ queryKey: ['articles'] });
        },
    });
};


// User management hooks (admin only)
export const useUsers = () => {
    return useQuery({
        queryKey: ['users'],
        queryFn: () => authApi.listUsers(),
    });
};

export const useCreateUser = () => {
    const queryClient = useQueryClient();
    return useMutation({
        mutationFn: (data: { email: string; password: string; role: string }) =>
            authApi.createUser(data),
        onSuccess: () => {
            queryClient.invalidateQueries({ queryKey: ['users'] });
        },
    });
};

export const useDeleteUser = () => {
    const queryClient = useQueryClient();
    return useMutation({
        mutationFn: (userId: number) => authApi.deleteUser(userId),
        onSuccess: () => {
            queryClient.invalidateQueries({ queryKey: ['users'] });
        },
    });
};
