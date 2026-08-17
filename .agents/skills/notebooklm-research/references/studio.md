# NotebookLM Studio reference

Use runtime `studio_status(action="list_types")` as the option authority. The
0.9.0 research baseline exposes these artifact classes, but live schemas always win:

| Intent | `artifact_type` | Main options |
| --- | --- | --- |
| Podcast or spoken analysis | `audio` | `audio_format`, `audio_length`, `language`, `focus_prompt` |
| Explainer or narrative video | `video` | `video_format`, `visual_style`, `video_style_prompt`, `focus_prompt` |
| Written synthesis | `report` | `report_format`, `custom_prompt`, `language` |
| Presentation | `slide_deck` | `slide_format`, `slide_length`, `focus_prompt` |
| One-page visual | `infographic` | `orientation`, `detail_level`, `infographic_style`, `focus_prompt` |
| Concept map | `mind_map` | `title` |
| Multiple-choice assessment | `quiz` | `question_count`, `difficulty`, `focus_prompt` |
| Study cards | `flashcards` | `difficulty`, `focus_prompt` |
| Structured extraction | `data_table` | required explicit `description` with columns and row unit |

## Prompt contract

Keep ordinary prompts compact. Include:

1. audience and purpose;
2. two or three source-grounded topics;
3. output structure or decision to support;
4. `Use only the selected notebook sources. Mark unsupported or inferred items.`

Use a guided preview for high-stakes deliverables, cinematic video, ambiguous
audiences, or when the user asks to inspect the prompt. Otherwise infer sensible
format options from the requested artifact without an intake questionnaire.

## Lifecycle

1. Inspect existing artifacts before creating a duplicate. Existing artifacts may be
   used as exploration surfaces for focused notebook follow-up.
2. Obtain explicit generation intent.
3. Call `studio_create(..., confirm=True)` with selected `source_ids` when useful.
4. Poll the specific artifact with `studio_status` until `completed`, `failed`, or the
   bounded wait expires. The 0.9.0 server returns lean paginated status by default;
   request detailed prompt/source data only when it is needed.
5. Use `studio_revise` only for targeted slide changes; it creates a new artifact.
6. Download or export only for a requested deliverable, evidence, retention, or a
   concrete inspection limitation. `download_all_artifacts` is a bulk backup/export
   capability, never a default research step.

For mind-map branch exploration, use a live Studio interaction when available. If the
MCP has no node interaction method, prefer an authorized authenticated browser for
exact UI state or formulate a focused `notebook_query` from the node label/path and
disclose the semantic fallback. Do not download the corpus to simulate a click.

Research basis: `jacob-bd/notebooklm-mcp-cli` 0.9.0 at commit
`2f28855b1545ea321568be6e39dc8c2efb338dd5` (MIT). This reference is a concise
Agent OS adaptation; live MCP schemas take precedence over the upstream guide.
