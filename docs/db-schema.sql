-- MT5 infrastructure database schema + sanitized data
-- Generated: 2026-04-23T15:43:15Z
-- Sensitive fields (passwords, api_keys) replaced with '***REDACTED***'


-- ============================================================
-- Table: mt5_clients
-- ============================================================
                                                 Table "public.mt5_clients"
        Column        |            Type             | Collation | Nullable |                    Default                     
----------------------+-----------------------------+-----------+----------+------------------------------------------------
 client_id            | integer                     |           | not null | nextval('mt5_clients_client_id_seq'::regclass)
 account_id           | uuid                        |           | not null | 
 client_name          | character varying(100)      |           | not null | 
 mt5_login            | character varying(100)      |           | not null | 
 mt5_password         | character varying(256)      |           | not null | 
 mt5_server           | character varying(100)      |           | not null | 
 password_type        | character varying(20)       |           | not null | 'primary'::character varying
 proxy_id             | integer                     |           |          | 
 connection_status    | character varying(20)       |           | not null | 'disconnected'::character varying
 is_active            | boolean                     |           | not null | true
 priority             | integer                     |           | not null | 0
 last_connected_at    | timestamp without time zone |           |          | 
 last_disconnected_at | timestamp without time zone |           |          | 
 total_connections    | integer                     |           | not null | 0
 failed_connections   | integer                     |           | not null | 0
 avg_latency_ms       | double precision            |           |          | 
 created_at           | timestamp without time zone |           | not null | now()
 updated_at           | timestamp without time zone |           | not null | now()
 created_by           | uuid                        |           |          | 
 bridge_url           | character varying(500)      |           |          | 
 is_system_service    | boolean                     |           | not null | false
 agent_instance_name  | character varying(100)      |           |          | 
 bridge_service_name  | character varying(100)      |           |          | 
 bridge_service_port  | integer                     |           |          | 
 mt5_path             | character varying(500)      |           |          | 
 mt5_data_path        | character varying(500)      |           |          | 
 role                 | character varying(20)       |           |          | 'trading'::character varying
Indexes:
    "mt5_clients_pkey" PRIMARY KEY, btree (client_id)
    "idx_mt5_clients_system_service" btree (is_system_service)
Foreign-key constraints:
    "mt5_clients_account_id_fkey" FOREIGN KEY (account_id) REFERENCES accounts(account_id) ON DELETE CASCADE
Referenced by:
    TABLE "mt5_instances" CONSTRAINT "mt5_instances_client_id_fkey" FOREIGN KEY (client_id) REFERENCES mt5_clients(client_id) ON DELETE CASCADE


-- Sanitized sample rows (passwords/secrets redacted)
 client_id | mt5_login |    mt5_server     |  mt5_password  | mt5_primary_pwd |        bridge_url         | bridge_service_port | bridge_service_name  | agent_instance_name  | is_active 
-----------+-----------+-------------------+----------------+-----------------+---------------------------+---------------------+----------------------+----------------------+-----------
        14 | 15015331  | ICMarketsSC-MT5-6 | ***REDACTED*** | ***REDACTED***  | http://172.31.14.113:8888 |                8888 | hustle-mt5-mt5-icsys | hustle-mt5-mt5-icsys | t
        15 | 2163899   | Bybit-Live-3      | ***REDACTED*** | ***REDACTED***  | http://172.31.14.113:8001 |                8001 | hustle-mt5-mt5-by01  | hustle-mt5-mt5-by01  | t
        16 | 6380983   | Bybit-Live-2      | ***REDACTED*** | ***REDACTED***  | http://172.31.14.113:8002 |                8002 | hustle-mt5-mt5-by02  | hustle-mt5-mt5-by02  | t
        17 | 15016910  | ICMarketsSC-MT5-6 | ***REDACTED*** | ***REDACTED***  | http://172.31.14.113:8021 |                8021 | hustle-mt5-mt5-ic01  | hustle-mt5-mt5-ic01  | t
        18 | 15017157  | ICMarketsSC-MT5-6 | ***REDACTED*** | ***REDACTED***  | http://172.31.14.113:8022 |                8022 | hustle-mt5-mt5-ic02  | hustle-mt5-mt5-ic02  | t
        19 | 2325036   | Bybit-Live-2      | ***REDACTED*** | ***REDACTED***  | http://172.31.14.113:8886 |                8886 | hustle-mt5-mt5-bysys | hustle-mt5-mt5-bysys | t
        20 | 3971962   | Bybit-Live-2      | ***REDACTED*** | ***REDACTED***  | http://172.31.14.113:8003 |                8003 | hustle-mt5-mt5-by03  | hustle-mt5-mt5-by03  | t
(7 rows)


-- ============================================================
-- Table: mt5_instances
-- ============================================================
                                   Table "public.mt5_instances"
    Column     |            Type             | Collation | Nullable |           Default            
---------------+-----------------------------+-----------+----------+------------------------------
 instance_id   | uuid                        |           | not null | gen_random_uuid()
 instance_name | character varying(100)      |           | not null | 
 server_ip     | character varying(50)       |           | not null | 
 service_port  | integer                     |           | not null | 
 mt5_path      | character varying(500)      |           | not null | 
 mt5_data_path | character varying(500)      |           |          | 
 is_portable   | boolean                     |           |          | false
 deploy_path   | character varying(500)      |           | not null | 
 auto_start    | boolean                     |           |          | true
 status        | character varying(20)       |           |          | 'stopped'::character varying
 is_active     | boolean                     |           |          | false
 created_at    | timestamp without time zone |           | not null | CURRENT_TIMESTAMP
 updated_at    | timestamp without time zone |           | not null | CURRENT_TIMESTAMP
 created_by    | uuid                        |           |          | 
 instance_type | character varying(20)       |           | not null | 'primary'::character varying
 client_id     | integer                     |           |          | 
Indexes:
    "mt5_instances_pkey" PRIMARY KEY, btree (instance_id)
    "idx_mt5_instances_active" btree (is_active)
    "idx_mt5_instances_client_id" btree (client_id)
    "idx_mt5_instances_client_type" UNIQUE, btree (client_id, instance_type) WHERE client_id IS NOT NULL
    "idx_mt5_instances_server_ip" btree (server_ip)
    "idx_mt5_instances_status" btree (status)
    "idx_mt5_instances_type" btree (instance_type)
    "mt5_instances_instance_name_key" UNIQUE CONSTRAINT, btree (instance_name)
    "mt5_instances_service_port_key" UNIQUE CONSTRAINT, btree (service_port)
Check constraints:
    "check_instance_type" CHECK (instance_type::text = ANY (ARRAY['primary'::character varying, 'backup'::character varying]::text[]))
Foreign-key constraints:
    "mt5_instances_client_id_fkey" FOREIGN KEY (client_id) REFERENCES mt5_clients(client_id) ON DELETE CASCADE


-- Sanitized sample rows (passwords/secrets redacted)
             instance_id              | instance_name  | client_id | instance_type |   server_ip   | service_port |                 mt5_path                 |       deploy_path       | status  | is_active 
--------------------------------------+----------------+-----------+---------------+---------------+--------------+------------------------------------------+-------------------------+---------+-----------
 ec64d3d4-a1b0-4141-84a7-a50d9f997884 | MT5 ICSYS-实例 |        14 | primary       | 172.31.14.113 |         8888 | D:\MetaTrader 5-mt5-icsys\terminal64.exe | D:\hustle-mt5-mt5-icsys | running | t
 86549262-383a-46b0-b9a4-6bdd7168a25f | MT5-BY01-实例  |        15 | primary       | 172.31.14.113 |         8001 | D:\MetaTrader 5-mt5-by01\terminal64.exe  | D:\hustle-mt5-mt5-by01  | running | t
 faa48f71-432a-4e70-8bd3-561da06a4e42 | MT5-BY02-实例  |        16 | primary       | 172.31.14.113 |         8002 | D:\MetaTrader 5-mt5-by02\terminal64.exe  | D:\hustle-mt5-mt5-by02  | running | t
 6253fd6d-c449-442d-bacc-e2630a8f3e2a | MT5-IC01-实例  |        17 | primary       | 172.31.14.113 |         8021 | D:\MetaTrader 5-mt5-ic01\terminal64.exe  | D:\hustle-mt5-mt5-ic01  | running | t
 461c073b-fa83-46c1-aa90-9341a959cb9a | MT5-IC02-实例  |        18 | primary       | 172.31.14.113 |         8022 | D:\MetaTrader 5-mt5-ic02\terminal64.exe  | D:\hustle-mt5-mt5-ic02  | running | t
 3747fa56-58b5-488b-b19b-38ced1204424 | MT5 BYSYS-实例 |        19 | primary       | 172.31.14.113 |         8886 | D:\MetaTrader 5-mt5-bysys\terminal64.exe | D:\hustle-mt5-mt5-bysys | running | t
 62cda6e7-c4a7-4e3b-a764-d8cd38dfa7d7 | MT5-BY03-实例  |        20 | primary       | 172.31.14.113 |         8003 | D:\MetaTrader 5-mt5-by03\terminal64.exe  | D:\hustle-mt5-mt5-by03  | running | t
(7 rows)


-- ============================================================
-- Table: mt5_config
-- ============================================================
                         Table "public.mt5_config"
   Column    |            Type             | Collation | Nullable | Default 
-------------+-----------------------------+-----------+----------+---------
 key         | character varying(100)      |           | not null | 
 value       | text                        |           | not null | 
 description | character varying(500)      |           |          | 
 updated_at  | timestamp without time zone |           |          | now()
Indexes:
    "mt5_config_pkey" PRIMARY KEY, btree (key)


-- Sanitized sample rows (passwords/secrets redacted)
            key            |           value           
---------------------------+---------------------------
 agent_api_key             | ***REDACTED***
 agent_url                 | http://172.31.14.113:8765
 bridge_api_key            | ***REDACTED***
 health_check_interval_sec | 30
 tick_stale_threshold_sec  | 30
(5 rows)

