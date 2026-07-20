import { useCallback, useEffect, useRef, useState } from 'react';

import type { PlaygroundWorkspace } from './workspace';
import type {
  WorkspaceLoadResult,
  WorkspaceRepository,
} from './workspace-repository';

export type PersistencePhase =
  | 'restoring'
  | 'saved'
  | 'saving'
  | 'memory-only'
  | 'recovery-required';

export interface PersistentWorkspaceState {
  workspace: PlaygroundWorkspace;
  phase: PersistencePhase;
  recovery: {
    reason: 'invalid' | 'incompatible';
    raw: unknown;
  } | null;
  replace(
    workspace: PlaygroundWorkspace,
    options?: { immediate?: boolean },
  ): void;
  retry(): Promise<void>;
  reset(): Promise<void>;
}

export function usePersistentWorkspace({
  repository,
  defaultWorkspace,
  debounceMs = 300,
}: {
  repository: WorkspaceRepository;
  defaultWorkspace: PlaygroundWorkspace;
  debounceMs?: number;
}): PersistentWorkspaceState {
  const [workspace, setWorkspace] = useState(defaultWorkspace);
  const [phase, setPhase] = useState<PersistencePhase>('restoring');
  const [recovery, setRecovery] =
    useState<PersistentWorkspaceState['recovery']>(null);
  const workspaceRef = useRef(defaultWorkspace);
  const dirtyRef = useRef(false);
  const timerRef = useRef<ReturnType<typeof setTimeout> | null>(null);
  const saveSequenceRef = useRef(0);
  const mountedRef = useRef(true);

  const save = useCallback(
    async (snapshot: PlaygroundWorkspace): Promise<void> => {
      const sequence = saveSequenceRef.current + 1;
      saveSequenceRef.current = sequence;
      try {
        await repository.save(snapshot);
        if (
          mountedRef.current &&
          sequence === saveSequenceRef.current &&
          workspaceRef.current.revision === snapshot.revision
        ) {
          dirtyRef.current = false;
          setPhase('saved');
        }
      } catch {
        if (mountedRef.current && sequence === saveSequenceRef.current) {
          setPhase('memory-only');
        }
      }
    },
    [repository],
  );

  const scheduleSave = useCallback(
    (snapshot: PlaygroundWorkspace, immediate = false): void => {
      if (timerRef.current !== null) {
        clearTimeout(timerRef.current);
      }
      setPhase('saving');
      if (immediate) {
        timerRef.current = null;
        void save(snapshot);
        return;
      }
      timerRef.current = setTimeout(() => {
        timerRef.current = null;
        void save(snapshot);
      }, debounceMs);
    },
    [debounceMs, save],
  );

  const applyLoadResult = useCallback(
    async (result: WorkspaceLoadResult): Promise<void> => {
      if (result.status === 'ready') {
        workspaceRef.current = result.workspace;
        dirtyRef.current = false;
        setWorkspace(result.workspace);
        setRecovery(null);
        setPhase('saved');
      } else if (result.status === 'missing') {
        workspaceRef.current = defaultWorkspace;
        dirtyRef.current = true;
        setWorkspace(defaultWorkspace);
        setRecovery(null);
        scheduleSave(defaultWorkspace, true);
      } else {
        dirtyRef.current = false;
        setRecovery({ reason: result.reason, raw: result.raw });
        setPhase('recovery-required');
      }
    },
    [defaultWorkspace, scheduleSave],
  );

  useEffect(() => {
    mountedRef.current = true;
    void repository.load(defaultWorkspace.id).then(applyLoadResult, () => {
      if (mountedRef.current) {
        setPhase('memory-only');
      }
    });
    return () => {
      mountedRef.current = false;
      if (timerRef.current !== null) {
        clearTimeout(timerRef.current);
      }
    };
  }, [applyLoadResult, defaultWorkspace.id, repository]);

  useEffect(() => {
    const handlePageHide = (): void => {
      if (dirtyRef.current) {
        void save(workspaceRef.current);
      }
    };
    window.addEventListener('pagehide', handlePageHide);
    return () => window.removeEventListener('pagehide', handlePageHide);
  }, [save]);

  const replace = useCallback(
    (
      nextWorkspace: PlaygroundWorkspace,
      options?: { immediate?: boolean },
    ): void => {
      workspaceRef.current = nextWorkspace;
      dirtyRef.current = true;
      setWorkspace(nextWorkspace);
      setRecovery(null);
      scheduleSave(nextWorkspace, options?.immediate);
    },
    [scheduleSave],
  );

  const retry = useCallback(async (): Promise<void> => {
    if (dirtyRef.current) {
      scheduleSave(workspaceRef.current, true);
      return;
    }
    setPhase('restoring');
    try {
      await applyLoadResult(await repository.load(defaultWorkspace.id));
    } catch {
      setPhase('memory-only');
    }
  }, [
    applyLoadResult,
    defaultWorkspace.id,
    repository,
    scheduleSave,
  ]);

  const reset = useCallback(async (): Promise<void> => {
    await repository.remove(defaultWorkspace.id);
    workspaceRef.current = defaultWorkspace;
    dirtyRef.current = true;
    setWorkspace(defaultWorkspace);
    setRecovery(null);
    scheduleSave(defaultWorkspace, true);
  }, [defaultWorkspace, repository, scheduleSave]);

  return { workspace, phase, recovery, replace, retry, reset };
}
