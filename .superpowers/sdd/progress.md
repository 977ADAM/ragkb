# SDD progress feat/postgres-sqlalchemy

Task 1: complete (commits 905676a..a71cb29, review clean)

Task 2: complete (commits a71cb29..7729886, review clean)
# minors: MessageRow.id Integer vs BIGSERIAL; needs_database untested

Task 3: complete (commits 7729886..1ae93db, review clean)

Task 4: complete (commits 1ae93db..872daed, review clean)

Task 5: complete (commits 872daed..fb11310, review clean after stream_message fix)

Task 6: complete (commits fb11310..66f3e1d, review Important fixed)

Task 7: complete (commits 66f3e1d..2d2fd88, review clean)

Whole-branch review (Important): `.env.example` placeholder password; `make backend`
sets `RAGKB_HISTORY_ENABLED=false` (bool parse in `_apply_env`); session + history
off uses `EphemeralHistory` while `PostgresAccounts` stays. Tests in `test_guard`
and `test_session_auth`.
