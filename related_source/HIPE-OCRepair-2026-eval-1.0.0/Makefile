.DEFAULT_GOAL := help

PYTHON        := venv/bin/python

# --- Real pipeline paths ---
REFERENCE_DIR          ?= data/reference
SUBMISSIONS_DIR        ?= data/systems
PER_RUN_DIR            := results/per-run
RANKINGS_DIR           := results/system-rankings
RESULTS_MD             := HIPE_OCRepair_2026_evaluation_results.md
TEXT_VIEWS_DIR         := results/text-views
TEXT_VIEWS_DIR_NORMALIZED := results/text-views-normalized

# --- Dummy pipeline paths (isolated from real pipeline) ---
REFERENCE_DIR_DUMMY    ?= data/reference-dummy
SUBMISSIONS_DUMMY_DIR  ?= data/systems-dummy
PER_RUN_DIR_DUMMY      := results-dummy/per-run
RANKINGS_DIR_DUMMY     := results-dummy/system-rankings
RESULTS_MD_DUMMY       := HIPE_OCRepair_2026_evaluation_results_dummy.md
TEXT_VIEWS_DIR_DUMMY   := results-dummy/text-views
TEXT_VIEWS_DIR_DUMMY_NORMALIZED := results-dummy/text-views-normalized
DUMMY_BASELINE_SWAP_CHARS ?= 0.05 0.1
DUMMY_BASELINE_SWAP_WORDS ?= 0.01 0.05
DUMMY_BASELINE_RUN_SEEDS  ?= --run-seeds
SCHEMA_PATH         ?= lib/schema.json
EXPORT_TEXT_VIEWS_APPLY_NORMALIZATIONS ?= 0
EXPORT_TEXT_VIEWS_NORMALIZE_FLAG := $(if $(filter 1 true yes on,$(EXPORT_TEXT_VIEWS_APPLY_NORMALIZATIONS)),--apply-normalizations,)

TEAMS_JSON         := lib/teams.json
COMPETITION_CONFIG := lib/competition_config.json
SCORER_VERSION     := 0.9.9
DATA_VERSION       := v0.9

SUBMISSIONS           := $(wildcard $(SUBMISSIONS_DIR)/*.jsonl)
PER_RUN_JSONS         := $(patsubst $(SUBMISSIONS_DIR)/%.jsonl,$(PER_RUN_DIR)/%.json,$(SUBMISSIONS))
REFERENCE_FILES       := $(wildcard $(REFERENCE_DIR)/*.jsonl)
REFERENCE_FILES_DUMMY := $(wildcard $(REFERENCE_DIR_DUMMY)/*.jsonl)

$(PER_RUN_DIR):
	mkdir -p $@
$(RANKINGS_DIR):
	mkdir -p $@
$(TEXT_VIEWS_DIR):
	mkdir -p $@
$(TEXT_VIEWS_DIR_NORMALIZED):
	mkdir -p $@
$(PER_RUN_DIR_DUMMY):
	mkdir -p $@
$(RANKINGS_DIR_DUMMY):
	mkdir -p $@
$(TEXT_VIEWS_DIR_DUMMY):
	mkdir -p $@
$(TEXT_VIEWS_DIR_DUMMY_NORMALIZED):
	mkdir -p $@
$(SUBMISSIONS_DUMMY_DIR):
	mkdir -p $@

$(PER_RUN_DIR)/%.json: $(SUBMISSIONS_DIR)/%.jsonl | $(PER_RUN_DIR)
	$(PYTHON) lib/score_one.py --hypothesis $< --reference-dir $(REFERENCE_DIR) --output $@ --log-file $@.log

.PHONY: baselines-dummy
baselines-dummy: | $(SUBMISSIONS_DUMMY_DIR)
	$(PYTHON) lib/create_dummy_baselines.py \
		--output-dir $(SUBMISSIONS_DUMMY_DIR) \
		--swap-chars $(DUMMY_BASELINE_SWAP_CHARS) \
		--swap-words $(DUMMY_BASELINE_SWAP_WORDS) \
		$(DUMMY_BASELINE_RUN_SEEDS) \
		$(REFERENCE_FILES_DUMMY)

.PHONY: baseline-no-correction
baseline-no-correction: | $(SUBMISSIONS_DIR)
	$(PYTHON) lib/create_dummy_baselines.py \
		$(REFERENCE_FILES) \
		--output-dir $(SUBMISSIONS_DIR) \
		--strategies baseline-no-correction \
		

.PHONY: score
score: $(PER_RUN_JSONS)

.PHONY: export-text-views
export-text-views: | $(TEXT_VIEWS_DIR)
	for f in $(SUBMISSIONS_DIR)/*.jsonl; do \
		stem=$$(basename $$f .jsonl); \
		$(PYTHON) lib/export_text_views.py --hypothesis $$f --reference-dir $(REFERENCE_DIR) --output-prefix $(TEXT_VIEWS_DIR)/$$stem --log-file $(TEXT_VIEWS_DIR)/$$stem.log $(EXPORT_TEXT_VIEWS_NORMALIZE_FLAG); \
	done

.PHONY: export-text-views-normalized
export-text-views-normalized: | $(TEXT_VIEWS_DIR_NORMALIZED)
	for f in $(SUBMISSIONS_DIR)/*.jsonl; do \
		stem=$$(basename $$f .jsonl); \
		$(PYTHON) lib/export_text_views.py --hypothesis $$f --reference-dir $(REFERENCE_DIR) --output-prefix $(TEXT_VIEWS_DIR_NORMALIZED)/$$stem --log-file $(TEXT_VIEWS_DIR_NORMALIZED)/$$stem.log --apply-normalizations; \
	done

.PHONY: validate-submissions
validate-submissions:
	$(PYTHON) lib/validate_submissions.py --input-dir $(SUBMISSIONS_DIR) $(if $(SCHEMA_PATH),--schema $(SCHEMA_PATH),)

.PHONY: validate-submissions-dummy
validate-submissions-dummy:
	$(PYTHON) lib/validate_submissions.py --input-dir $(SUBMISSIONS_DUMMY_DIR) $(if $(SCHEMA_PATH),--schema $(SCHEMA_PATH),)

.PHONY: score-dummy
score-dummy: | $(PER_RUN_DIR_DUMMY)
	for f in $(SUBMISSIONS_DUMMY_DIR)/*.jsonl; do \
		stem=$$(basename $$f .jsonl); \
		$(PYTHON) lib/score_one.py --hypothesis $$f --reference-dir $(REFERENCE_DIR_DUMMY) --output $(PER_RUN_DIR_DUMMY)/$$stem.json --log-file $(PER_RUN_DIR_DUMMY)/$$stem.json.log; \
	done

.PHONY: export-text-views-dummy
export-text-views-dummy: | $(TEXT_VIEWS_DIR_DUMMY)
	for f in $(SUBMISSIONS_DUMMY_DIR)/*.jsonl; do \
		stem=$$(basename $$f .jsonl); \
		$(PYTHON) lib/export_text_views.py --hypothesis $$f --reference-dir $(REFERENCE_DIR_DUMMY) --output-prefix $(TEXT_VIEWS_DIR_DUMMY)/$$stem --log-file $(TEXT_VIEWS_DIR_DUMMY)/$$stem.log $(EXPORT_TEXT_VIEWS_NORMALIZE_FLAG); \
	done

.PHONY: export-text-views-dummy-normalized
export-text-views-dummy-normalized: | $(TEXT_VIEWS_DIR_DUMMY_NORMALIZED)
	for f in $(SUBMISSIONS_DUMMY_DIR)/*.jsonl; do \
		stem=$$(basename $$f .jsonl); \
		$(PYTHON) lib/export_text_views.py --hypothesis $$f --reference-dir $(REFERENCE_DIR_DUMMY) --output-prefix $(TEXT_VIEWS_DIR_DUMMY_NORMALIZED)/$$stem --log-file $(TEXT_VIEWS_DIR_DUMMY_NORMALIZED)/$$stem.log --apply-normalizations; \
	done

.PHONY: rankings
rankings: $(PER_RUN_JSONS) | $(RANKINGS_DIR)
	$(PYTHON) lib/build_rankings.py --per-run-dir $(PER_RUN_DIR) --output-dir $(RANKINGS_DIR) --competition-config $(COMPETITION_CONFIG)

.PHONY: rankings-dummy
rankings-dummy: | $(RANKINGS_DIR_DUMMY)
	$(PYTHON) lib/build_rankings.py --per-run-dir $(PER_RUN_DIR_DUMMY) --output-dir $(RANKINGS_DIR_DUMMY) --competition-config $(COMPETITION_CONFIG)

.PHONY: results-md-dummy
results-md-dummy: | $(RANKINGS_DIR_DUMMY)
	$(PYTHON) lib/build_results_md.py --rankings-dir $(RANKINGS_DIR_DUMMY) --teams-json $(TEAMS_JSON) --output $(RESULTS_MD_DUMMY) --scorer-version $(SCORER_VERSION) --data-version $(DATA_VERSION)

.PHONY: results-md
results-md: | $(RANKINGS_DIR)
	$(PYTHON) lib/build_results_md.py --rankings-dir $(RANKINGS_DIR) --teams-json $(TEAMS_JSON) --output $(RESULTS_MD) --scorer-version $(SCORER_VERSION) --data-version $(DATA_VERSION)

.PHONY: pairwise-overlaps
pairwise-overlaps: | $(RANKINGS_DIR)
	$(PYTHON) lib/pairwise_overlaps.py \
		--rankings-dir $(RANKINGS_DIR) \
		--submissions-dir $(SUBMISSIONS_DIR) \
		--reference-dir $(REFERENCE_DIR) \
		--metric cmer_micro \
		--n-bootstrap 10000 \
		--output results/pairwise-overlaps.tsv \
		--verbose

.PHONY: pairwise-overlaps-dummy
pairwise-overlaps-dummy: | $(RANKINGS_DIR_DUMMY)
	$(PYTHON) lib/pairwise_overlaps.py \
		--rankings-dir $(RANKINGS_DIR_DUMMY) \
		--submissions-dir $(SUBMISSIONS_DUMMY_DIR) \
		--reference-dir $(REFERENCE_DIR_DUMMY) \
		--metric cmer_micro \
		--n-bootstrap 10000 \
		--output results-dummy/pairwise-overlaps.tsv \
		--verbose


.PHONY: eval-full
eval-full: 
	$(MAKE) score
	$(MAKE) rankings
	$(MAKE) results-md
	$(MAKE) export-text-views
	$(MAKE) export-text-views-normalized
	$(MAKE) pairwise-overlaps

.PHONY: eval-full-dummy
eval-full-dummy:
	$(MAKE) clean-dummy
	$(MAKE) baselines-dummy
	$(MAKE) score-dummy
	$(MAKE) rankings-dummy results-md-dummy

.PHONY: eval-full-refresh
eval-full-refresh:
	rm -rf $(PER_RUN_DIR) $(RANKINGS_DIR) $(TEXT_VIEWS_DIR) $(TEXT_VIEWS_DIR_NORMALIZED) $(RESULTS_MD)
	rm -f results/pairwise-overlaps.tsv
	$(MAKE) eval-full


.PHONY: clean-dummy
clean-dummy:
	find $(SUBMISSIONS_DUMMY_DIR) -maxdepth 1 \( -name 'perfect_*.jsonl' -o -name 'no-correction_*.jsonl' -o -name 'char-swaps-*.jsonl' -o -name 'word-swaps-*.jsonl' -o -name 'same_*.jsonl' -o -name 'random_*.jsonl' \) -delete
	rm -rf $(PER_RUN_DIR_DUMMY) $(RANKINGS_DIR_DUMMY) $(TEXT_VIEWS_DIR_DUMMY) $(TEXT_VIEWS_DIR_DUMMY_NORMALIZED) $(RESULTS_MD_DUMMY)

.PHONY: clean
clean:
	rm -rf $(PER_RUN_DIR) $(RANKINGS_DIR) $(TEXT_VIEWS_DIR) $(TEXT_VIEWS_DIR_NORMALIZED) $(RESULTS_MD)
	rm -f results/pairwise-overlaps.tsv

.PHONY: help
help:
	@echo ""
	@echo "HIPE-OCRepair-2026 evaluation pipeline"
	@echo ""
	@echo "End-to-end targets:"
	@echo "  eval-full          Score real submissions, build rankings, results MD, text views, and pairwise tests (uses results/)"
	@echo "  eval-full-refresh  Remove all derived real files and re-run eval-full from scratch"
	@echo ""
	@echo "Pipeline step-by-step (all output under results/):"
	@echo "  validate-submissions  Validate real submissions in $(SUBMISSIONS_DIR) against the JSON schema"
	@echo "  baseline-no-correction  Generate no-correction baseline from real reference files"
	@echo "  export-text-views  Export aligned orig/gth/cor multiline text files to results/text-views/"
	@echo "  export-text-views-normalized  Export with evaluator normalization to results/text-views-normalized/"
	@echo "  score              Score real submissions in $(SUBMISSIONS_DIR) (incremental)"
	@echo "  rankings           Build ranking TSVs from scored real submissions"
	@echo "  results-md         Render $(RESULTS_MD)"
	@echo "  pairwise-overlaps  Test systems with overlapping CIs (outputs results/pairwise-overlaps.tsv)"
	@echo ""
	@echo "Statistical Analysis:"
	@echo "  pairwise-overlaps  Identify consecutive systems with overlapping CIs and run paired bootstrap tests"
	@echo "                     Output: results/pairwise-overlaps.tsv with significance testing results"
	@echo "                     Use cases: (1) Validate ranking differences are statistically meaningful"
	@echo "                                (2) Identify performance 'tiers' (systems in statistical tie)"
	@echo "                                (3) Detect misleading rankings (point estimate differs but not significant)"
	@echo ""
	@echo "Utilities:"
	@echo "  clean              Remove results/, $(RESULTS_MD)"
	@echo ""
	@echo "Override variables:"
	@echo "  REFERENCE_DIR        Real reference JSONL directory     (default: data/reference)"
	@echo "  SCHEMA_PATH          Optional JSON schema override      (default: lib/schema.json)"
	@echo "  EXPORT_TEXT_VIEWS_APPLY_NORMALIZATIONS  1/true to pass --apply-normalizations (default: $(EXPORT_TEXT_VIEWS_APPLY_NORMALIZATIONS))"
	@echo ""
