"use client";

import { TriangleAlert } from "lucide-react";

import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { cn } from "@/lib/utils";
import type { ModelInfo, ProviderInfo } from "@/types/chat";

interface Props {
  provider: string | null;
  model: string | null;
  /** Only providers that have an API key — see `useModelSelection`. */
  providers: ProviderInfo[];
  providerInfo: ProviderInfo | null;
  models: ModelInfo[];
  modelSource: "api" | "config" | null;
  modelError: string | null;
  disabled?: boolean;
  onProviderChange: (name: string) => void;
  onModelChange: (id: string) => void;
}

/** "131K" — much easier to read at a glance than 131072. */
function contextSize(m: ModelInfo): string | null {
  if (!m.context_window) return null;
  const k = Math.round(m.context_window / 1000);
  return k >= 1000 ? `${Math.round(k / 1000)}M context` : `${k}K context`;
}

function describeModel(m: ModelInfo): string {
  return [m.owned_by, contextSize(m)].filter(Boolean).join(" · ");
}

export function ModelPicker({
  provider,
  model,
  providers,
  providerInfo,
  models,
  modelSource,
  modelError,
  disabled = false,
  onProviderChange,
  onModelChange,
}: Props) {
  if (providers.length === 0) {
    return (
      <p className="flex items-center gap-1.5 px-1 text-xs text-[var(--muted-foreground)]">
        <TriangleAlert aria-hidden className="size-3.5 shrink-0" />
        No provider has an API key yet. Add one on the Settings page.
      </p>
    );
  }

  const warning =
    modelSource === "config" && modelError
      ? `Short list — ${modelError}`
      : providerInfo && !providerInfo.supports_tool_calling
        ? "This provider can't call tools"
        : null;

  return (
    <div className="flex min-w-0 flex-1 items-center gap-1.5">
      <Select
        value={provider ?? ""}
        onValueChange={onProviderChange}
        disabled={disabled}
      >
        <SelectTrigger aria-label="Provider" className="shrink-0">
          <SelectValue />
        </SelectTrigger>

        <SelectContent>
          {providers.map((p) => (
            <SelectItem
              key={p.name}
              value={p.name}
              description={p.supports_tool_calling ? undefined : "can't call tools"}
            >
              {p.name}
            </SelectItem>
          ))}
        </SelectContent>
      </Select>

      <Select
        value={model ?? ""}
        onValueChange={onModelChange}
        disabled={disabled || models.length === 0}
      >
        <SelectTrigger
          aria-label="Model"
          // Model names can be very long; let it shrink and truncate instead of
          // pushing the send button out of the frame.
          className="min-w-0 max-w-[16rem] flex-1 [&>span]:truncate"
        >
          <SelectValue placeholder="Choose a model" />
        </SelectTrigger>

        <SelectContent className="max-w-[22rem]">
          {models.map((m) => (
            <SelectItem key={m.id} value={m.id} description={describeModel(m) || undefined}>
              {m.label}
            </SelectItem>
          ))}
        </SelectContent>
      </Select>

      {warning && (
        <span
          title={warning}
          className={cn(
            "hidden items-center gap-1 text-xs sm:flex",
            "text-amber-600 dark:text-amber-400",
          )}
        >
          <TriangleAlert aria-hidden className="size-3.5 shrink-0" />
          <span className="max-w-[12rem] truncate">{warning}</span>
        </span>
      )}
    </div>
  );
}
