"use client";

import { SkillRunList, ToolRunList } from "@/components/skills/execution-log";
import { SectionHeader } from "@/components/skills/shared";

/** Two short lists rather than one merged feed: they page independently on
 * the backend, and merging two paginated sources by date would reorder rows
 * every time "Show more" loaded a page from only one of them. */
export function RunHistoryPanel({ description }: { description: string }) {
  return (
    <>
      <SectionHeader title="Run history" description={description} />
      <div className="space-y-10">
        <section aria-labelledby="skill-runs-title">
          <h3 id="skill-runs-title" className="mb-3 text-sm font-semibold">
            Skill scripts
          </h3>
          <SkillRunList
            skill={null}
            emptyHint="When the assistant runs a skill's script from chat, or an engineer runs one from the skill's page, it shows up here with its output."
          />
        </section>
        <section aria-labelledby="tool-runs-title">
          <h3 id="tool-runs-title" className="mb-3 text-sm font-semibold">
            Tools run by hand
          </h3>
          <ToolRunList />
        </section>
      </div>
    </>
  );
}
