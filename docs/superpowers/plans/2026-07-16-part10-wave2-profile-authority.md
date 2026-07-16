# Part 10 Wave 2 Profile Authority Plan

**Goal:** Make the server-confirmed active model profile the only value rendered by ChatPage.

## Tasks

- [x] Confirm the switch adapter re-reads `/settings` and rejects mismatched active profiles.
- [x] Add a source boundary test forbidding ChatPage-local selected profile truth.
- [x] Derive the active model button and menu state from `data.settings.activeProfile`.
- [x] Keep only `switchingModel` as transient UI state during the request.
- [x] Run profile/settings focused Python and Desktop tests plus production build.
- [x] Run full closure verification, update canonical documents, and commit.
