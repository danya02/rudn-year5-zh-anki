LESSON_FILES := $(wildcard lesson_data/*.txt)
STAMPS       := $(patsubst lesson_data/%.txt,.processed/%.stamp,$(LESSON_FILES))
PYTHON       := pipenv run python3

.PHONY: all add-sentences add-audio clean

all: chinese.apkg prompt.txt

# Rebuild deck and prompt whenever any lesson stamp changes.
# add-sentences and add-audio call build internally, so they keep chinese.apkg
# up-to-date on their own.
chinese.apkg: $(STAMPS)
	$(PYTHON) pipeline.py add-audio

prompt.txt: $(STAMPS)
	$(PYTHON) pipeline.py gen-prompt

# Process one lesson file; stamp records that it has been ingested.
# Re-touch the lesson file (or delete its stamp) to reprocess it.
.processed/%.stamp: lesson_data/%.txt | .processed
	$(PYTHON) pipeline.py add-words -i $<
	@touch $@

.processed:
	@mkdir -p .processed

SENTENCES ?= sentences.json

add-sentences:
	$(PYTHON) pipeline.py add-sentences $(SENTENCES) $(if $(LESSON),--lesson $(LESSON),)

add-audio:
	$(PYTHON) pipeline.py add-audio

clean:
	rm -f chinese.apkg prompt.txt
	rm -rf .processed
