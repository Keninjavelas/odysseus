# Product expansion: projects, evaluations, and Understanding Studio

This is the implementation ledger for the November 2026 expansion. A checked
foundation means the named API or workflow exists; it does not imply the full
product experience described later in the roadmap is complete.

## Working foundations

- The Windows release smoke starts the app in an isolated environment and
  verifies chat and core APIs. The smoke command is `python scripts/odysseus-smoke`.
- Model context windows already drive input budgets and tool retrieval width.
  The agent now keeps the reduced always-available tool set through fallback
  and recovery routes for small context windows. The
  `agent_context_profile` setting accepts `auto`, `4k`, `8k`, or `16k` and
  caps discovered context conservatively.
- `manage_notes` supports `list_open` and `append_item` for turning research,
  email, or meeting findings into an existing checklist without replacing it.
- `/api/projects` provides owner-scoped project metadata and chat assignment.
  `/api/sessions?project_id=<id>` lists a project's conversations.
- `/api/evals/cases` saves evaluation prompts and tool/response expectations.
  Submit canonical traces to `/api/evals/cases/<id>/grade`, then compare two
  stored runs via `/api/evals/compare/<left>/<right>`.
- `/api/studio/episodes` compiles a line-based outline into a saved video,
  narration, and captions timeline. Its GPU-free preview contains shot cards
  and silent audio. `PATCH /api/studio/episodes/<id>/timeline` can edit shot
  text, duration, and order, then regenerate the MP4 preview.
- `/lab` exposes project creation and chat assignment, saved evaluation cases
  and trace grading, and the studio storyboard editor in the browser.

## Next implementation gates

1. **Project context isolation.** Add project IDs to notes, documents, memory,
   research, and media records, and require project filters in agent retrieval.
   The current project API organizes chats; it does not isolate those resources.
2. **Small-model measurement.** Expose the profile switch in the graphical
   settings, measure prompt and tool-schema token use, and run saved eval
   cases against each profile. The setting and budget cap work today; the
   comparative dashboard remains to build.
3. **Evaluation runner and view.** Wire saved cases to live model execution,
   trace capture, latency/token/cost metrics, and a UI for case/run comparison.
   Current grading accepts an existing canonical trace and is offline.
4. **Action inbox.** Add an explicit review queue for tasks extracted from
   email, research, and meeting notes, with source links and duplicate checks.
   Current `append_item` is the persistence primitive.
5. **Studio production mode.** Add sourced outline research, schema-validated
   shot expansion, continuity bible, local image/TTS providers, voiceover,
   subtitles, and background FFmpeg jobs. The current preview uses placeholders.
6. **NLE editing.** Add split/trim/ripple operations, multiple video and audio
   tracks, transitions, keyframes, waveform and proxy generation, and export
   presets. Interchange should map the timeline to OpenTimelineIO once the
   multi-track model is stable.

## New use cases to explore

### Premiere-style editing and Understanding Studio

- **Transcript-first rough cut:** import interview audio, transcribe locally,
  select sentences, and create a cut with corresponding source timecodes.
- **Evidence-aware documentary:** each narration claim points to its source
  document and time range; unsupported claims are flagged before rendering.
- **Screen recording to tutorial:** detect cursor actions and pauses, assemble
  chapters, captions, zooms, and a short version for social platforms.
- **Multilingual versioning:** keep one editorial timeline while generating
  dubbed narration, translated captions, and locale-specific title cards.
- **Review handoff:** reviewers annotate time ranges, editors turn comments
  into shot-level tasks, and exports retain a version manifest.
- **Accessibility pass:** caption readability, audio description gaps, loudness,
  flashing-frame checks, and alternative text for stills.

### Other domains

- **Research desk:** source-backed reading lists, claim maps, and daily change
  reports with citations and uncertainty labels.
- **Education:** a lesson outline becomes slides, narrated clips, practice
  questions, and a student-facing source pack.
- **Community archive:** ingest scans, recordings, and oral histories; build
  searchable collections and consent-aware public exhibits.
- **Software maintenance:** compare a deployment against saved evals, summarize
  regressions, and turn failures into an owner-scoped project action list.
- **Personal operations:** summarize commitments from mail and notes into a
  reviewable weekly plan with direct links to the originating records.

The first three studio ideas share the same timeline and transcript provenance
model, so building them together should avoid three separate editing stacks.
