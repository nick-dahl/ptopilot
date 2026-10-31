# Hidden gems: the session routine

Gems are written in working sessions between the owner and Claude; nothing drafts them in
production. The catalogue is one YAML file per gem in `ptopilot/data/gems/`, written to
[the style guide](style-guide.md). Only `approved` gems are ever shown; publishing is a commit and
push.

## Each session

1. **Check the catalogue.** Run

   ```
   python -m ptopilot.gems check
   ```

   It validates every file in the folder (exit 1 on any invalid file, naming it) and lists the
   claims last checked more than 12 months ago.
2. **Retire stale gems.** Re-check each stale claim against its source and update `checked_on`; if a
   claim no longer holds and the write-up can't be fixed, set the gem's `status: retired`. Retired
   gems leave every feed, but their guide page stays open for people who were sent them.
3. **Draft new gems** as `status: draft`, following the style guide, checking each claim against
   its source as it goes into `claims`. Aim for a spread across trip styles.
4. **Review.** The owner reads each draft and approves it or rejects it with a note.
   - Approved: set `status: approved` and `approved_on` to today's date.
   - Rejected: redraft that gem in the same session from the note, and append the note's lesson to
     the style guide's "Notes from the owner" as a short rule or example.
5. **Commit and push.** Run `python -m ptopilot.gems check` once more, then commit the gem files
   and the style guide and push to `main`.

## Pointing at another folder

`PTOPILOT_GEMS_DIR` makes the app and the pipeline read gems from another folder (the tests use
`tests/fixtures/gems`); `python -m ptopilot.gems check --folder DIR` checks one.
