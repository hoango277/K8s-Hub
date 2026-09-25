"use client";

import { useCallback, useMemo } from "react";
import { useQuery, useQueryClient } from "@tanstack/react-query";

import { api } from "@/lib/api";
import { useLocalStorage } from "@/hooks/use-local-storage";
import { qk } from "@/lib/query-keys";
import type { ModelCatalog, ProvidersView } from "@/types/chat";

const STORAGE_KEY = "k8shub.llm";

/** The user's provider and model choice for the chat panel. */
export interface ModelChoice {
  provider: string | null;
  model: string | null;
}

const NO_CHOICE: ModelChoice = { provider: null, model: null };

function parseChoice(raw: string | null): ModelChoice {
  if (!raw) return NO_CHOICE;
  try {
    const d = JSON.parse(raw) as Partial<ModelChoice>;
    return {
      provider: typeof d.provider === "string" ? d.provider : null,
      model: typeof d.model === "string" ? d.model : null,
    };
  } catch {
    // Old data in a broken format — treat as no choice, don't break the page.
    return NO_CHOICE;
  }
}

export function useProviders() {
  return useQuery({
    queryKey: qk.chat.providers,
    queryFn: () => api.get<ProvidersView>("/chat/providers"),
    staleTime: 5 * 60 * 1000,
  });
}

export function useModels(provider: string | null) {
  return useQuery({
    queryKey: qk.chat.models(provider ?? ""),
    queryFn: () => api.get<ModelCatalog>(`/chat/models?provider=${provider}`),
    enabled: Boolean(provider),
    // The backend already caches for 10 minutes and never returns an error, so
    // don't ask again every time the tab regains focus.
    staleTime: 5 * 60 * 1000,
    refetchOnWindowFocus: false,
  });
}

/**
 * Manages the provider + model choice for the chat panel.
 *
 * The choice is remembered in the browser. With nothing chosen, the system
 * configuration applies — so users can chat without ever touching these two
 * pickers.
 */
export function useModelSelection() {
  const qc = useQueryClient();
  const providers = useProviders();

  // The choice stored in the browser. Writing here also updates state, so the
  // user sees the change immediately.
  const [raw, saveRaw] = useLocalStorage(STORAGE_KEY);
  const choice = useMemo(() => parseChoice(raw), [raw]);

  // Only show providers that have an API key. Offering a provider that is sure
  // to fail is a trap: the error only surfaces after the user has typed their
  // question and pressed send.
  const available = useMemo(
    () => (providers.data?.providers ?? []).filter((p) => p.api_key_set),
    [providers.data],
  );

  const systemDefault = providers.data?.current.provider ?? null;

  // The selected provider must be one of the usable ones. If the system config
  // points at a provider without a key, fall back to the first usable one.
  const provider =
    [choice.provider, systemDefault].find((t) => t && available.some((p) => p.name === t)) ??
    available[0]?.name ??
    null;

  const modelsQuery = useModels(provider);

  // The selected model must belong to the selected provider. After switching
  // providers, the old model is no longer valid and must be dropped.
  const models = modelsQuery.data?.models ?? [];
  const validChosenModel =
    choice.model && models.some((m) => m.id === choice.model) ? choice.model : null;

  const providerInfo = available.find((p) => p.name === provider) ?? null;

  /** Only accept a model if it's actually in the list being shown.
   *
   * A picker given a value that matches no item shows up blank, yet the user
   * can still press send — and then gets an error from the provider. */
  const ifListed = (id: string | null | undefined) =>
    id && models.some((m) => m.id === id) ? id : null;

  const model =
    validChosenModel ??
    // Same provider the system is set to: follow the system's model.
    (provider === systemDefault ? ifListed(providers.data?.current.model) : null) ??
    // A different provider: use ITS default model.
    //
    // Without this step we'd fall through to the first item of the
    // alphabetically sorted list — for Google that's "antigravity-preview", a
    // slow and expensive research model. The default must be an everyday model.
    ifListed(providerInfo?.default_model) ??
    models[0]?.id ??
    null;

  const save = useCallback(
    (next: ModelChoice) => saveRaw(JSON.stringify(next)),
    [saveRaw],
  );

  const setProvider = useCallback(
    (name: string) => {
      // Drop the old model: it belongs to a different provider.
      save({ provider: name, model: null });
      void qc.prefetchQuery({
        queryKey: qk.chat.models(name),
        queryFn: () => api.get<ModelCatalog>(`/chat/models?provider=${name}`),
      });
    },
    [save, qc],
  );

  const setModel = useCallback(
    (id: string) => save({ provider, model: id }),
    [save, provider],
  );

  return {
    provider,
    model,
    providers: available,
    providerInfo,
    models,
    modelSource: modelsQuery.data?.source ?? null,
    modelError: modelsQuery.data?.error ?? null,
    isLoading: providers.isLoading || modelsQuery.isLoading,
    setProvider,
    setModel,
  };
}
