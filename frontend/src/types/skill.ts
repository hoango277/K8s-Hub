/**
 * Agent Skills — matches the models in backend/app/api/v1/skills.py.
 * Change one side, change the other.
 *
 * A skill is a folder: SKILL.md (YAML front matter + instructions) plus
 * optional scripts/, references/ and assets/. Not to be confused with a Tool
 * (types/tool.ts), which is code the assistant calls.
 */

export type SkillSource = "builtin" | "custom";

export interface SkillFile {
  path: string;
  size: number;
}

export interface SkillSummary {
  name: string;
  description: string;
  /** builtin = folder in the repo (read-only here), custom = created or imported on the web. */
  source: SkillSource;
  enabled: boolean;
  files: SkillFile[];
}

export interface SkillDetail extends SkillSummary {
  skill_md: string;
  frontmatter: Record<string, unknown>;
}

export interface SkillCreate {
  name: string;
  description: string;
  instructions: string;
}

export interface SkillFileContent {
  path: string;
  /** null when the file is binary. */
  text: string | null;
  size: number;
}

export interface SkillRun {
  id: string;
  skill: string;
  script: string;
  args: string[];
  trigger: "chat" | "manual";
  actor_email: string;
  ok: boolean;
  exit_code: number | null;
  output: string;
  duration_ms: number;
  created_at: string;
}

export interface SkillRunPage {
  items: SkillRun[];
  total: number;
}
