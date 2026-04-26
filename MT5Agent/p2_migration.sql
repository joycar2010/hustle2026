BEGIN;

ALTER TABLE accounts ADD COLUMN IF NOT EXISTS status varchar(20) NOT NULL DEFAULT 'active';

UPDATE accounts SET status = CASE WHEN is_active THEN 'active' ELSE 'disabled' END;

CREATE OR REPLACE FUNCTION trg_accounts_status_to_is_active() RETURNS trigger AS $$
BEGIN
  IF NEW.status IS DISTINCT FROM OLD.status THEN
    NEW.is_active := (NEW.status = 'active');
  END IF;
  RETURN NEW;
END;
$$ LANGUAGE plpgsql;

DROP TRIGGER IF EXISTS accounts_status_sync ON accounts;
CREATE TRIGGER accounts_status_sync
  BEFORE UPDATE ON accounts
  FOR EACH ROW EXECUTE FUNCTION trg_accounts_status_to_is_active();

CREATE OR REPLACE FUNCTION trg_accounts_is_active_to_status() RETURNS trigger AS $$
BEGIN
  IF NEW.is_active IS DISTINCT FROM OLD.is_active THEN
    NEW.status := CASE WHEN NEW.is_active THEN 'active' ELSE 'disabled' END;
  END IF;
  RETURN NEW;
END;
$$ LANGUAGE plpgsql;

DROP TRIGGER IF EXISTS accounts_is_active_sync ON accounts;
CREATE TRIGGER accounts_is_active_sync
  BEFORE UPDATE ON accounts
  FOR EACH ROW EXECUTE FUNCTION trg_accounts_is_active_to_status();

COMMIT;
