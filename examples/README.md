# Examples

Every command in the main README's *Usage* section runs from the repository root with these files. Outputs go to `output/` (git-ignored).

| Path | What it is | Used by |
| --- | --- | --- |
| `requests.txt` | A translation-workflow request | `chatdify generate -f examples/requests.txt` |
| `inputs/meeting_notes.md` | Fictional meeting notes, a test input for dynamic validation | `--input-file` for the meeting-summary request and for `dsl/meeting_minutes.yml` |
| `dsl/` | Workflows that pass static validation (CI runs `chatdify validate examples/dsl`) | `validate`, `modify`, `chat` |
| `broken/text_summarization.yml` | A code node imports `nltk` (not in the Dify sandbox) and returns a field named `error` | `validate` (fails on purpose), `fix` |
| `config.toml` | Full configuration template; copy to `~/.chatdify/config.toml` and fill in the `<...>` values | setup |
| `env.sh.example` | The same settings as environment variables | setup |

The LLM nodes in `dsl/` and `broken/` use the default workflow model, `deepseek-v4-flash` from `langgenius/deepseek/deepseek`. If your Dify does not have it, change `model.name` / `model.provider` in these files before running them on Dify. `audio_script.yml` also needs an OpenAI-compatible `tts-1` model.

```bash
# static validation only (needs the Dify source + chatdify[dify]); no LLM, finishes in seconds
chatdify validate examples/dsl examples/broken

# repair the broken workflow, passing the runtime error seen in Dify
chatdify fix examples/broken/text_summarization.yml \
  --feedback "code node 2: ModuleNotFoundError: No module named 'nltk'" -o output/fixed.yml

# generate from the request file
chatdify generate -f examples/requests.txt -o output/translate.yml

# generate a workflow that takes a document, validated with the sample notes
chatdify generate "Summarize the uploaded meeting notes and list the action items with owners and due dates" \
  --input-file examples/inputs/meeting_notes.md -o output/meeting_summary.yml

# modify an example workflow
chatdify modify examples/dsl/audio_script.yml \
  "Remove the TTS step and output the generated script directly" -o output/audio_script_v2.yml

# run an example on your Dify (dynamic validation)
chatdify validate examples/dsl/meeting_minutes.yml --dynamic --input-file examples/inputs/meeting_notes.md \
  --request "Summarize uploaded meeting notes by section, by speaker, and as action items"
```
