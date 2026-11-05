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
- `/api/actions` and `/lab` provide a source-linked review queue. A proposed
  task can be accepted into an owner-owned checklist or rejected; duplicate
  proposals and duplicate checklist items are detected. The lab can extract
  explicitly marked TODO, Action, Next step, Follow up, and unchecked checklist
  lines from a note into proposals. Note, document, and saved research report
  proposals link directly to their source. Accepting one into a checklist
  requires the same project. Research launched from a project chat persists
  that assignment with its report. Standalone research can select a project
  when it starts, and the research library API can filter by project. The
  `manage_research` agent tool lists, reads, and deletes only reports owned by
  the current user and assigned to the current chat's project. Saved reports
  can be reassigned in Project Lab; deleting a project returns its reports to
  General along with its chats, notes, and documents.
- The inbox message menu can propose explicitly marked tasks from an email
  without marking it read. Proposals retain the account, folder, and UID so
  Project Lab can reopen the originating message before checklist acceptance.
- `/api/projects` provides owner-scoped project metadata and chat assignment.
  `/api/sessions?project_id=<id>` lists a project's conversations. Notes can
  also be assigned to a project; the Notes agent tool reads and writes within
  the current chat's project. Documents have project membership too: documents
  created in a project chat inherit it, existing documents can be assigned in
  Project Lab, and the document library accepts `project_id` to filter results
  and language facets. Document agent actions, their approval binding, and chat
  document injection check the current chat's project. Project deletion unassigns
  documents without deleting them.
- Chat memory recall and the `manage_memory` agent tool see global memories plus
  the current project's memories. New chat memories carry a project ID;
  existing owner-matched session memories are tagged on startup. Moving a chat
  or deleting its project updates associated memory assignments. The native
  memory provider accepts session context for scoped recall and deletion, and
  scheduled consolidation keeps owners and projects separate. The owner-wide
  Memory settings view can still manage all of that owner's records.
- `/api/evals/cases` saves evaluation prompts and tool/response expectations.
  Submit canonical traces to `/api/evals/cases/<id>/grade`, then compare two
  stored runs via `/api/evals/compare/<left>/<right>`. Project Lab can also
  start a fresh read-only evaluation chat against a configured model, capture
  its native SSE trace, and grade it. When the run reports metrics, the lab
  shows response time, token use, and context utilization. Run history and
  selectable pairwise comparisons are visible in the lab; missing metrics are
  labeled unavailable rather than treated as zero.
- `/api/studio/episodes` compiles a line-based outline into a saved video,
  narration, and captions timeline. Its GPU-free preview contains shot cards
  and silent audio. `PATCH /api/studio/episodes/<id>/timeline` can edit shot
  text, duration, and order, split or delete shots with ripple timing, then
  regenerate the MP4 preview. Local PNG, JPEG, and WebP stills can be attached
  to shots, and local narration audio can be attached to the corresponding
  audio lane and mixed into the preview. A shot can also generate voiceover
  from its text through the configured local or endpoint TTS provider; this
  requires an explicit click and FFmpeg. The caption lane exports as SRT and
  is embedded as a selectable subtitle track in the MP4. Timeline edits use
  revision checks so a stale browser tab receives a conflict instead of
  overwriting a newer edit. The saved episode list lets users reopen timelines
  after a page refresh. A UTF-8 SRT transcript can also create a silent rough
  cut with cue source timecodes and editable pause shots; preview rendering can
  be requested separately. This import currently accepts up to 60 shots and
  five minutes. The original interview audio can be attached once and played
  from the matching source ranges, including pauses. An MP4, MOV, WebM, or MKV
  interview can also be attached to cut moving source video by cue timecode;
  its audio fills shots without a separate voice track. Original media stays
  owner-private. Episodes can be created in a project, filtered or reassigned
  in Project Lab, and return to General when their project is deleted. Local
  transcription and background rendering are still pending.
- `/lab` exposes project creation and chat assignment, saved evaluation cases
  and trace grading, and the studio storyboard editor in the browser.

## Next implementation gates

1. **Complete project context isolation.** Add project IDs to uploads and other media
   records, and require project filters in all remaining agent retrieval.
   Chats, Notes, and Documents now have project assignments and their main agent
   paths filter by project. Chat-originated research now carries a project, but
   memory recall and writes now distinguish global from project records.
   Studio episodes have project membership, while unfiltered manual research
   browsing, other document retrieval, uploads, and media outside Studio still
   need a full isolation audit and filters.
2. **Small-model measurement.** Measure prompt and tool-schema token use, and
   run saved eval cases against each profile. The settings switch and budget
   cap work today; the comparative dashboard remains to build.
3. **Evaluation measurement and view.** Add cost and provider-verified latency
   metrics, repeatable model and profile sweeps, and trend charts across runs.
   The current live runner uses plan mode, so effectful tool workflows still
   need isolated disposable fixtures before they can be evaluated safely.
4. **Automatic action extraction.** Connect meeting pipelines to the review
   queue with verifiable source deep links. Email, note, document, and saved
   research report extraction handle explicit task markers; unmarked prose,
   recurring inbox scanning, and external sources still need parsers and source
   verification. Research launched from a project chat retains that project in
   its saved report.
5. **Studio production mode.** Add sourced outline research, schema-validated
   shot expansion, continuity bible, generated stills, batch voiceover,
   multilingual subtitle generation, and background FFmpeg jobs. The current preview uses placeholders
   where a shot has no attached still.
6. **NLE editing.** Expand basic split/delete ripple edits with clip trim,
   multiple video and audio
   tracks, transitions, keyframes, waveform and proxy generation, and export
   presets. Interchange should map the timeline to OpenTimelineIO once the
   multi-track model is stable.

## New use cases to explore

### Premiere-style editing and Understanding Studio

- **Transcript-first rough cut:** timed SRT import and original audio/video cuts
  are built. Next, transcribe locally and select sentences
  to cut the original media with corresponding source timecodes.
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
