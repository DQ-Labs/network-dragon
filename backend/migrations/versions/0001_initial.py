"""Frozen initial schema: independent of future ORM changes."""

from alembic import op

revision = "0001"
down_revision = None

STATEMENTS = [
    "CREATE TABLE audit_log (\n\tid VARCHAR NOT NULL, \n\tat FLOAT NOT NULL, \n\taction VARCHAR NOT NULL, \n\tsubject VARCHAR NOT NULL, \n\tfacts JSON NOT NULL, \n\tPRIMARY KEY (id)\n)",
    'CREATE TABLE login_limits (\n\t"key" VARCHAR NOT NULL, \n\tcount INTEGER NOT NULL, \n\texpires FLOAT NOT NULL, \n\tPRIMARY KEY ("key")\n)',
    "CREATE TABLE networks (\n\tid VARCHAR NOT NULL, \n\tname VARCHAR(120) NOT NULL, \n\tcidr VARCHAR NOT NULL, \n\tinterface VARCHAR NOT NULL, \n\tmode VARCHAR NOT NULL, \n\tenabled BOOLEAN NOT NULL, \n\tbaseline BOOLEAN NOT NULL, \n\tlast_discovery FLOAT, \n\thealth VARCHAR NOT NULL, \n\thealth_reason VARCHAR NOT NULL, \n\tlast_guard_ack FLOAT, \n\tPRIMARY KEY (id)\n)",
    "CREATE TABLE scan_profiles (\n\tid VARCHAR NOT NULL, \n\tname VARCHAR NOT NULL, \n\tkind VARCHAR NOT NULL, \n\trevision INTEGER NOT NULL, \n\tports VARCHAR NOT NULL, \n\tbudget INTEGER NOT NULL, \n\tenrichment BOOLEAN NOT NULL, \n\tPRIMARY KEY (id)\n)",
    "CREATE TABLE sessions (\n\ttoken_hash VARCHAR NOT NULL, \n\tcsrf VARCHAR NOT NULL, \n\texpires FLOAT NOT NULL, \n\tPRIMARY KEY (token_hash)\n)",
    'CREATE TABLE settings (\n\t"key" VARCHAR NOT NULL, \n\tvalue JSON NOT NULL, \n\tPRIMARY KEY ("key")\n)',
    "CREATE TABLE users (\n\tid INTEGER NOT NULL, \n\tpassword_hash VARCHAR NOT NULL, \n\tPRIMARY KEY (id)\n)",
    "CREATE TABLE worker_lease (\n\tid INTEGER NOT NULL, \n\towner VARCHAR NOT NULL, \n\tgeneration INTEGER NOT NULL, \n\texpires FLOAT NOT NULL, \n\theartbeat FLOAT NOT NULL, \n\tPRIMARY KEY (id)\n)",
    "CREATE TABLE devices (\n\tid VARCHAR NOT NULL, \n\tnetwork_id VARCHAR NOT NULL, \n\tidentity VARCHAR NOT NULL, \n\tmac VARCHAR, \n\tconfidence VARCHAR NOT NULL, \n\tip VARCHAR NOT NULL, \n\thostname VARCHAR NOT NULL, \n\tname VARCHAR NOT NULL, \n\tnotes TEXT NOT NULL, \n\tacknowledged BOOLEAN NOT NULL, \n\twatched BOOLEAN NOT NULL, \n\tarchived BOOLEAN NOT NULL, \n\tmonitored BOOLEAN NOT NULL, \n\tcanonical_id VARCHAR, \n\tpresence VARCHAR NOT NULL, \n\tfirst_seen FLOAT NOT NULL, \n\tlast_seen FLOAT NOT NULL, \n\tlast_evidence FLOAT NOT NULL, \n\tmisses INTEGER NOT NULL, \n\tmute_until FLOAT, \n\tepisode VARCHAR, \n\tlast_notified FLOAT, \n\tPRIMARY KEY (id), \n\tUNIQUE (network_id, identity), \n\tFOREIGN KEY(network_id) REFERENCES networks (id), \n\tFOREIGN KEY(canonical_id) REFERENCES devices (id)\n)",
    "CREATE INDEX ix_devices_network_id ON devices (network_id)",
    "CREATE INDEX ix_devices_presence ON devices (presence)",
    'CREATE TABLE scan_jobs (\n\tid VARCHAR NOT NULL, \n\t"key" VARCHAR NOT NULL, \n\tnetwork_id VARCHAR NOT NULL, \n\tprofile_id VARCHAR NOT NULL, \n\ttarget VARCHAR NOT NULL, \n\tstatus VARCHAR NOT NULL, \n\tcreated_at FLOAT NOT NULL, \n\tstarted_at FLOAT, \n\tfinished_at FLOAT, \n\towner VARCHAR, \n\tgeneration INTEGER NOT NULL, \n\tlease_until FLOAT, \n\tattempts INTEGER NOT NULL, \n\tcancel_requested BOOLEAN NOT NULL, \n\terror VARCHAR NOT NULL, \n\tPRIMARY KEY (id), \n\tUNIQUE ("key"), \n\tFOREIGN KEY(network_id) REFERENCES networks (id), \n\tFOREIGN KEY(profile_id) REFERENCES scan_profiles (id)\n)',
    "CREATE INDEX ix_scan_jobs_status ON scan_jobs (status)",
    "CREATE TABLE device_addresses (\n\tid VARCHAR NOT NULL, \n\tdevice_id VARCHAR NOT NULL, \n\taddress VARCHAR NOT NULL, \n\tfamily INTEGER NOT NULL, \n\tfirst_seen FLOAT NOT NULL, \n\tlast_seen FLOAT NOT NULL, \n\tended_at FLOAT, \n\tPRIMARY KEY (id), \n\tFOREIGN KEY(device_id) REFERENCES devices (id)\n)",
    "CREATE INDEX ix_device_addresses_device_id ON device_addresses (device_id)",
    "CREATE TABLE scan_runs (\n\tid VARCHAR NOT NULL, \n\tnetwork_id VARCHAR NOT NULL, \n\tjob_id VARCHAR, \n\tkind VARCHAR NOT NULL, \n\tsource VARCHAR NOT NULL, \n\tobserved_at FLOAT NOT NULL, \n\tstatus VARCHAR NOT NULL, \n\thealth_reason VARCHAR NOT NULL, \n\tcoverage JSON NOT NULL, \n\tchecksum VARCHAR NOT NULL, \n\tversion VARCHAR NOT NULL, \n\tprofile_revision VARCHAR NOT NULL, \n\targuments JSON NOT NULL, \n\tPRIMARY KEY (id), \n\tFOREIGN KEY(network_id) REFERENCES networks (id), \n\tFOREIGN KEY(job_id) REFERENCES scan_jobs (id)\n)",
    "CREATE INDEX ix_scan_runs_network_id ON scan_runs (network_id)",
    "CREATE INDEX ix_scan_runs_observed_at ON scan_runs (observed_at)",
    "CREATE TABLE current_ports (\n\tid VARCHAR NOT NULL, \n\tdevice_id VARCHAR NOT NULL, \n\trun_id VARCHAR NOT NULL, \n\tobserved_at FLOAT NOT NULL, \n\tport INTEGER NOT NULL, \n\tprotocol VARCHAR NOT NULL, \n\tstate VARCHAR NOT NULL, \n\tfacts JSON NOT NULL, \n\tPRIMARY KEY (id), \n\tUNIQUE (device_id, protocol, port), \n\tFOREIGN KEY(device_id) REFERENCES devices (id), \n\tFOREIGN KEY(run_id) REFERENCES scan_runs (id)\n)",
    "CREATE INDEX ix_current_ports_device_id ON current_ports (device_id)",
    'CREATE TABLE events (\n\tid VARCHAR NOT NULL, \n\t"key" VARCHAR NOT NULL, \n\tdevice_id VARCHAR, \n\tnetwork_id VARCHAR NOT NULL, \n\trun_id VARCHAR, \n\ttype VARCHAR NOT NULL, \n\tat FLOAT NOT NULL, \n\tbaseline BOOLEAN NOT NULL, \n\tfacts JSON NOT NULL, \n\tepisode VARCHAR, \n\tPRIMARY KEY (id), \n\tUNIQUE ("key"), \n\tFOREIGN KEY(device_id) REFERENCES devices (id), \n\tFOREIGN KEY(network_id) REFERENCES networks (id), \n\tFOREIGN KEY(run_id) REFERENCES scan_runs (id)\n)',
    "CREATE INDEX ix_events_at ON events (at)",
    "CREATE INDEX ix_events_device_id ON events (device_id)",
    "CREATE INDEX ix_events_type ON events (type)",
    "CREATE TABLE host_observations (\n\tid VARCHAR NOT NULL, \n\trun_id VARCHAR NOT NULL, \n\tdevice_id VARCHAR NOT NULL, \n\tobserved_at FLOAT NOT NULL, \n\tfacts JSON NOT NULL, \n\tPRIMARY KEY (id), \n\tFOREIGN KEY(run_id) REFERENCES scan_runs (id), \n\tFOREIGN KEY(device_id) REFERENCES devices (id)\n)",
    "CREATE INDEX ix_host_observations_device_id ON host_observations (device_id)",
    "CREATE INDEX ix_host_observations_observed_at ON host_observations (observed_at)",
    "CREATE INDEX ix_host_observations_run_id ON host_observations (run_id)",
    "CREATE TABLE port_observations (\n\tid VARCHAR NOT NULL, \n\trun_id VARCHAR NOT NULL, \n\tdevice_id VARCHAR NOT NULL, \n\tobserved_at FLOAT NOT NULL, \n\tport INTEGER NOT NULL, \n\tprotocol VARCHAR NOT NULL, \n\tfacts JSON NOT NULL, \n\tPRIMARY KEY (id), \n\tFOREIGN KEY(run_id) REFERENCES scan_runs (id), \n\tFOREIGN KEY(device_id) REFERENCES devices (id)\n)",
    "CREATE INDEX ix_port_observations_device_id ON port_observations (device_id)",
    "CREATE INDEX ix_port_observations_observed_at ON port_observations (observed_at)",
    "CREATE INDEX ix_port_observations_run_id ON port_observations (run_id)",
    "CREATE TABLE notification_outbox (\n\tid VARCHAR NOT NULL, \n\tevent_id VARCHAR NOT NULL, \n\tstatus VARCHAR NOT NULL, \n\treason VARCHAR NOT NULL, \n\tattempts INTEGER NOT NULL, \n\tnext_attempt FLOAT NOT NULL, \n\taccepted_at FLOAT, \n\tPRIMARY KEY (id), \n\tUNIQUE (event_id), \n\tFOREIGN KEY(event_id) REFERENCES events (id)\n)",
    "CREATE INDEX ix_notification_outbox_next_attempt ON notification_outbox (next_attempt)",
    "CREATE INDEX ix_notification_outbox_status ON notification_outbox (status)",
    "CREATE TABLE delivery_attempts (\n\tid VARCHAR NOT NULL, \n\toutbox_id VARCHAR NOT NULL, \n\tat FLOAT NOT NULL, \n\toutcome VARCHAR NOT NULL, \n\tPRIMARY KEY (id), \n\tFOREIGN KEY(outbox_id) REFERENCES notification_outbox (id)\n)",
    "CREATE INDEX ix_delivery_attempts_at ON delivery_attempts (at)",
    "CREATE INDEX ix_delivery_attempts_outbox_id ON delivery_attempts (outbox_id)",
]


def upgrade():
    for statement in STATEMENTS:
        op.get_bind().exec_driver_sql(statement)


def downgrade():
    raise RuntimeError("Restore a verified backup; destructive downgrade is unsupported")
