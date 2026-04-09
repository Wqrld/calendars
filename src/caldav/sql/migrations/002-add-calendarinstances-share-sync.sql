-- Add is_sync_managed and share_access_level to calendarinstances.
-- Used by InternalApiPlugin (mailbox ACL sync) and ShareAccessPlugin
-- (freebusy-only sharing). Introduced alongside the Messages mailbox
-- integration but the corresponding migration was missing, so existing
-- deploys lack these columns and the plugins fail with
-- "column does not exist" errors.
-- Idempotent: safe to run multiple times.

DO $$ BEGIN
  IF NOT EXISTS (SELECT FROM information_schema.columns
    WHERE table_name='calendarinstances' AND column_name='is_sync_managed') THEN
    ALTER TABLE calendarinstances
      ADD COLUMN is_sync_managed BOOLEAN NOT NULL DEFAULT FALSE;
  END IF;

  IF NOT EXISTS (SELECT FROM information_schema.columns
    WHERE table_name='calendarinstances' AND column_name='share_access_level') THEN
    ALTER TABLE calendarinstances
      ADD COLUMN share_access_level VARCHAR(50);
  END IF;
END $$;
