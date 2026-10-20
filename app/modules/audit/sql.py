"""SQL du déclencheur qui rend `audit_logs` en ajout seul (PostgreSQL).

Partagé entre la migration et le test qui prouve que la base refuse réellement toute modification.
"""

APPEND_ONLY_UP = """
CREATE OR REPLACE FUNCTION audit_logs_forbid_change() RETURNS trigger AS $$
BEGIN
    RAISE EXCEPTION 'audit_logs est en ajout seul : % interdit', TG_OP
        USING ERRCODE = 'insufficient_privilege';
END;
$$ LANGUAGE plpgsql;

CREATE TRIGGER audit_logs_append_only
    BEFORE UPDATE OR DELETE ON audit_logs
    FOR EACH ROW EXECUTE FUNCTION audit_logs_forbid_change();

CREATE TRIGGER audit_logs_no_truncate
    BEFORE TRUNCATE ON audit_logs
    FOR EACH STATEMENT EXECUTE FUNCTION audit_logs_forbid_change();
"""

APPEND_ONLY_DOWN = """
DROP TRIGGER IF EXISTS audit_logs_no_truncate ON audit_logs;
DROP TRIGGER IF EXISTS audit_logs_append_only ON audit_logs;
DROP FUNCTION IF EXISTS audit_logs_forbid_change();
"""
