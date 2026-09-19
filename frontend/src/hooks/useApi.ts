/**
 * React Query hooks for data fetching and caching.
 */
import { useEffect, useRef } from 'react';
import { useQuery, useMutation, useQueryClient, keepPreviousData } from '@tanstack/react-query';
import { articlesApi, summariesApi, topicsApi, settingsApi, statsApi, feedsApi, authApi, bulletinApi, playgroundApi, promptsApi } from '../services/api';
import type { ArticleFilters, UserSettings, BulletinGenerateRequest, ReprocessRequest, PlaygroundRunRequest } from '../types';

// Articles hooks
export const useArticleCounts = () => {
    return useQuery({
        queryKey: ['articleCounts'],
        queryFn: () => articlesApi.getCounts(),
        staleTime: 30000,
        refetchInterval: 60000,
    });
};

export const useArticles = (filters: ArticleFilters = {}) => {
    return useQuery({
        queryKey: ['articles', filters],
        queryFn: () => articlesApi.list(filters),
        staleTime: 30000,
        refetchInterval: 60000, // Poll every 60s to catch scheduler-added articles
        placeholderData: keepPreviousData, // keep current page visible while the next loads
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
            queryClient.invalidateQueries({ queryKey: ['articleCounts'] });
            queryClient.invalidateQueries({ queryKey: ['topics'] });
        },
    });
};

export const useMarkArticleRead = () => {
    const queryClient = useQueryClient();
    return useMutation({
        mutationFn: (articleId: number) => articlesApi.markRead(articleId),
        onSuccess: () => {
            queryClient.invalidateQueries({ queryKey: ['articles'] });
            queryClient.invalidateQueries({ queryKey: ['articleCounts'] });
        },
    });
};

export const useSetArticleStarred = () => {
    const queryClient = useQueryClient();
    return useMutation({
        mutationFn: ({ articleId, starred }: { articleId: number; starred: boolean }) =>
            articlesApi.setStarred(articleId, starred),
        onSuccess: () => {
            queryClient.invalidateQueries({ queryKey: ['articles'] });
            queryClient.invalidateQueries({ queryKey: ['articleCounts'] });
        },
    });
};

export const useUnstarAll = () => {
    const queryClient = useQueryClient();
    return useMutation({
        mutationFn: () => articlesApi.unstarAll(),
        onSuccess: () => {
            queryClient.invalidateQueries({ queryKey: ['articles'] });
            queryClient.invalidateQueries({ queryKey: ['articleCounts'] });
        },
    });
};

// Re-run "Error" articles (no severity label) through the classification + summary workflow.
export const useReprocessArticles = () => {
    const queryClient = useQueryClient();
    return useMutation({
        mutationFn: (payload: ReprocessRequest) => articlesApi.reprocess(payload),
        onSuccess: () => {
            queryClient.invalidateQueries({ queryKey: ['reprocessStatus'] });
            queryClient.invalidateQueries({ queryKey: ['articles'] });
            queryClient.invalidateQueries({ queryKey: ['articleCounts'] });
        },
    });
};

// Progress of the background re-process job. Polls every 2s while it runs and refreshes
// the article lists/counts whenever another article finishes.
export const useReprocessStatus = () => {
    const queryClient = useQueryClient();
    const query = useQuery({
        queryKey: ['reprocessStatus'],
        queryFn: () => articlesApi.getReprocessStatus(),
        refetchInterval: (q) => (q.state.data?.status === 'running' ? 2000 : false),
    });

    const done = query.data?.done;
    const status = query.data?.status;
    const prevStatus = useRef<typeof status>(undefined);
    useEffect(() => {
        // Only refresh while a run is in progress (or right as it finishes) — not on mount
        // when a stale "done" from an earlier run is still reported by the server.
        const wasRunning = prevStatus.current === 'running';
        prevStatus.current = status;
        if (status !== 'running' && !wasRunning) return;
        queryClient.invalidateQueries({ queryKey: ['articles'] });
        queryClient.invalidateQueries({ queryKey: ['articleCounts'] });
    }, [done, status, queryClient]);

    return query;
};

export const useMarkArticlesBulkRead = () => {
    const queryClient = useQueryClient();
    return useMutation({
        mutationFn: ({ articleIds, filters }: { articleIds?: number[]; filters?: ArticleFilters }) =>
            articlesApi.markBulkRead(articleIds, filters),
        onSuccess: () => {
            queryClient.invalidateQueries({ queryKey: ['articles'] });
            queryClient.invalidateQueries({ queryKey: ['articleCounts'] });
            queryClient.invalidateQueries({ queryKey: ['topics'] });
        },
    });
};

export const useDeleteAllArticlesByPriority = () => {
    const queryClient = useQueryClient();
    return useMutation({
        mutationFn: ({ priority, feedIds }: { priority: string; feedIds?: number[] }) =>
            articlesApi.deleteAllByPriority(priority, feedIds),
        onSuccess: () => {
            queryClient.invalidateQueries({ queryKey: ['articles'] });
            queryClient.invalidateQueries({ queryKey: ['articleCounts'] });
            queryClient.invalidateQueries({ queryKey: ['topics'] });
        },
    });
};

export const useArchiveAllArticlesByPriority = () => {
    const queryClient = useQueryClient();
    return useMutation({
        mutationFn: ({ priority, feedIds }: { priority: string; feedIds?: number[] }) =>
            articlesApi.archiveAllByPriority(priority, feedIds),
        onSuccess: () => {
            queryClient.invalidateQueries({ queryKey: ['articles'] });
            queryClient.invalidateQueries({ queryKey: ['articleCounts'] });
            queryClient.invalidateQueries({ queryKey: ['topics'] });
        },
    });
};

export const useDeleteAllUnimportant = () => {
    const queryClient = useQueryClient();
    return useMutation({
        mutationFn: ({ feedIds }: { feedIds?: number[] }) =>
            articlesApi.deleteAllUnimportant(feedIds),
        onSuccess: () => {
            queryClient.invalidateQueries({ queryKey: ['articles'] });
            queryClient.invalidateQueries({ queryKey: ['articleCounts'] });
            queryClient.invalidateQueries({ queryKey: ['topics'] });
        },
    });
};

export const useArchiveAllUnimportant = () => {
    const queryClient = useQueryClient();
    return useMutation({
        mutationFn: ({ feedIds }: { feedIds?: number[] }) =>
            articlesApi.archiveAllUnimportant(feedIds),
        onSuccess: () => {
            queryClient.invalidateQueries({ queryKey: ['articles'] });
            queryClient.invalidateQueries({ queryKey: ['articleCounts'] });
            queryClient.invalidateQueries({ queryKey: ['topics'] });
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
            // The classification prompt's locked part renders the live topic list.
            queryClient.invalidateQueries({ queryKey: ['promptLocked'] });
            queryClient.invalidateQueries({ queryKey: ['playgroundSettings'] });
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
            // The classification prompt's locked part renders the live topic list.
            queryClient.invalidateQueries({ queryKey: ['promptLocked'] });
            queryClient.invalidateQueries({ queryKey: ['playgroundSettings'] });
        },
    });
};

export const useDeleteTopic = () => {
    const queryClient = useQueryClient();

    return useMutation({
        mutationFn: (topicId: number) => topicsApi.delete(topicId),
        onSuccess: () => {
            queryClient.invalidateQueries({ queryKey: ['topics'] });
            // The classification prompt's locked part renders the live topic list.
            queryClient.invalidateQueries({ queryKey: ['promptLocked'] });
            queryClient.invalidateQueries({ queryKey: ['playgroundSettings'] });
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
            // The summarization prompt's locked part lists the enabled summary types.
            queryClient.invalidateQueries({ queryKey: ['promptLocked'] });
            queryClient.invalidateQueries({ queryKey: ['playgroundSettings'] });
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

export const useTestFeedConnection = () => {
    return useMutation({
        mutationFn: (url: string) => feedsApi.test(url),
    });
};

export const useDeleteFeed = () => {
    const queryClient = useQueryClient();
    return useMutation({
        mutationFn: (feedId: number) => feedsApi.delete(feedId),
        onSuccess: () => {
            queryClient.invalidateQueries({ queryKey: ['feeds'] });
            queryClient.invalidateQueries({ queryKey: ['articles'] });
            queryClient.invalidateQueries({ queryKey: ['articleCounts'] });
            queryClient.invalidateQueries({ queryKey: ['topics'] });
        },
    });
};

export const useUpdateFeed = () => {
    const queryClient = useQueryClient();
    return useMutation({
        mutationFn: ({ feedId, url, title }: { feedId: number; url?: string; title?: string }) =>
            feedsApi.update(feedId, { url, title }),
        onSuccess: () => {
            queryClient.invalidateQueries({ queryKey: ['feeds'] });
            queryClient.invalidateQueries({ queryKey: ['articles'] });
        },
    });
};

export const useRefreshFeed = () => {
    return useMutation({
        mutationFn: (feedId: number) => feedsApi.refresh(feedId),
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

// Bulletin hooks
export const useBulletinCategories = () => {
    return useQuery({
        queryKey: ['bulletinCategories'],
        queryFn: () => bulletinApi.listCategories(),
    });
};

export const useCreateBulletinCategory = () => {
    const queryClient = useQueryClient();
    return useMutation({
        mutationFn: (name: string) => bulletinApi.createCategory(name),
        onSuccess: () => {
            queryClient.invalidateQueries({ queryKey: ['bulletinCategories'] });
        },
    });
};

export const useUpdateBulletinCategory = () => {
    const queryClient = useQueryClient();
    return useMutation({
        mutationFn: ({ categoryId, name }: { categoryId: number; name: string }) =>
            bulletinApi.updateCategory(categoryId, name),
        onSuccess: () => {
            queryClient.invalidateQueries({ queryKey: ['bulletinCategories'] });
        },
    });
};

export const useDeleteBulletinCategory = () => {
    const queryClient = useQueryClient();
    return useMutation({
        mutationFn: (categoryId: number) => bulletinApi.deleteCategory(categoryId),
        onSuccess: () => {
            queryClient.invalidateQueries({ queryKey: ['bulletinCategories'] });
        },
    });
};

export const useReorderBulletinCategories = () => {
    const queryClient = useQueryClient();
    return useMutation({
        mutationFn: (orderedIds: number[]) => bulletinApi.reorderCategories(orderedIds),
        onSuccess: () => {
            queryClient.invalidateQueries({ queryKey: ['bulletinCategories'] });
        },
    });
};

export const useGenerateBulletin = () => {
    const queryClient = useQueryClient();
    return useMutation({
        mutationFn: (payload: BulletinGenerateRequest) => bulletinApi.generate(payload),
        onSuccess: () => {
            queryClient.invalidateQueries({ queryKey: ['generatedBulletins'] });
        },
        // responseType: 'blob' means the global mutation onError fallback can't
        // parse the error detail (it arrives as a Blob, not JSON) — the caller
        // extracts and toasts the real message itself, so suppress the
        // fallback's generic one here instead of showing both.
        onError: () => {},
    });
};

export const useBulletinPreviewCount = (params: BulletinGenerateRequest) => {
    return useQuery({
        queryKey: ['bulletinPreviewCount', params],
        queryFn: () => bulletinApi.previewCount(params),
        placeholderData: keepPreviousData,
    });
};

export const useGeneratedBulletins = () => {
    return useQuery({
        queryKey: ['generatedBulletins'],
        queryFn: () => bulletinApi.listGenerated(),
    });
};

export const useDownloadGeneratedBulletin = () => {
    return useMutation({
        mutationFn: (id: number) => bulletinApi.downloadGenerated(id),
        // Same blob-response reasoning as useGenerateBulletin's onError.
        onError: () => {},
    });
};

export const useDeleteGeneratedBulletin = () => {
    const queryClient = useQueryClient();
    return useMutation({
        mutationFn: (id: number) => bulletinApi.deleteGenerated(id),
        onSuccess: () => {
            queryClient.invalidateQueries({ queryKey: ['generatedBulletins'] });
        },
    });
};

// System prompt hooks
// The read-only part the pipeline appends to a prompt (null promptType = not needed, no request).
export const usePromptLocked = (promptType: string | null) => {
    return useQuery({
        queryKey: ['promptLocked', promptType],
        queryFn: () => promptsApi.getLocked(promptType!),
        enabled: promptType !== null,
    });
};

// Playground hooks
export const usePlaygroundSettings = () => {
    return useQuery({
        queryKey: ['playgroundSettings'],
        queryFn: () => playgroundApi.getSettings(),
    });
};

// A dry run persists nothing server-side, so there is no cache to invalidate.
export const useRunPlayground = () => {
    return useMutation({
        mutationFn: (request: PlaygroundRunRequest) => playgroundApi.run(request),
    });
};
