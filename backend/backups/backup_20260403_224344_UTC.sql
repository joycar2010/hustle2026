--
-- PostgreSQL database dump
--

\restrict Dx2D55naMQY4O28aZW3u9zX4PqV75TR039glIQoOVECHlRNsKEW6SIDyKblbczU

-- Dumped from database version 16.13 (Ubuntu 16.13-0ubuntu0.24.04.1)
-- Dumped by pg_dump version 16.13 (Ubuntu 16.13-0ubuntu0.24.04.1)

SET statement_timeout = 0;
SET lock_timeout = 0;
SET idle_in_transaction_session_timeout = 0;
SET client_encoding = 'UTF8';
SET standard_conforming_strings = on;
SELECT pg_catalog.set_config('search_path', '', false);
SET check_function_bodies = false;
SET xmloption = content;
SET client_min_messages = warning;
SET row_security = off;

--
-- Name: pgagent; Type: SCHEMA; Schema: -; Owner: postgres
--

CREATE SCHEMA pgagent;


ALTER SCHEMA pgagent OWNER TO postgres;

--
-- Name: SCHEMA pgagent; Type: COMMENT; Schema: -; Owner: postgres
--

COMMENT ON SCHEMA pgagent IS 'pgAgent system tables';


--
-- Name: public; Type: SCHEMA; Schema: -; Owner: postgres
--

-- *not* creating schema, since initdb creates it


ALTER SCHEMA public OWNER TO postgres;

--
-- Name: SCHEMA public; Type: COMMENT; Schema: -; Owner: postgres
--

COMMENT ON SCHEMA public IS '';


--
-- Name: adminpack; Type: EXTENSION; Schema: -; Owner: -
--

CREATE EXTENSION IF NOT EXISTS adminpack WITH SCHEMA pg_catalog;


--
-- Name: EXTENSION adminpack; Type: COMMENT; Schema: -; Owner: 
--

COMMENT ON EXTENSION adminpack IS 'administrative functions for PostgreSQL';


--
-- Name: pgcrypto; Type: EXTENSION; Schema: -; Owner: -
--

CREATE EXTENSION IF NOT EXISTS pgcrypto WITH SCHEMA public;


--
-- Name: EXTENSION pgcrypto; Type: COMMENT; Schema: -; Owner: 
--

COMMENT ON EXTENSION pgcrypto IS 'cryptographic functions';


--
-- Name: uuid-ossp; Type: EXTENSION; Schema: -; Owner: -
--

CREATE EXTENSION IF NOT EXISTS "uuid-ossp" WITH SCHEMA public;


--
-- Name: EXTENSION "uuid-ossp"; Type: COMMENT; Schema: -; Owner: 
--

COMMENT ON EXTENSION "uuid-ossp" IS 'generate universally unique identifiers (UUIDs)';


--
-- Name: update_updated_at_column(); Type: FUNCTION; Schema: public; Owner: postgres
--

CREATE FUNCTION public.update_updated_at_column() RETURNS trigger
    LANGUAGE plpgsql
    AS $$
BEGIN
    NEW.updated_at = CURRENT_TIMESTAMP;
    RETURN NEW;
END;
$$;


ALTER FUNCTION public.update_updated_at_column() OWNER TO postgres;

SET default_tablespace = '';

SET default_table_access_method = heap;

--
-- Name: account_snapshots; Type: TABLE; Schema: public; Owner: postgres
--

CREATE TABLE public.account_snapshots (
    snapshot_id uuid DEFAULT gen_random_uuid() NOT NULL,
    account_id uuid NOT NULL,
    total_assets double precision NOT NULL,
    available_assets double precision NOT NULL,
    net_assets double precision NOT NULL,
    total_position double precision DEFAULT 0.0,
    frozen_assets double precision DEFAULT 0.0,
    margin_balance double precision DEFAULT 0.0,
    margin_used double precision DEFAULT 0.0,
    margin_available double precision DEFAULT 0.0,
    unrealized_pnl double precision DEFAULT 0.0,
    daily_pnl double precision DEFAULT 0.0,
    risk_ratio double precision DEFAULT 0.0,
    "timestamp" timestamp without time zone DEFAULT CURRENT_TIMESTAMP
);


ALTER TABLE public.account_snapshots OWNER TO postgres;

--
-- Name: accounts; Type: TABLE; Schema: public; Owner: postgres
--

CREATE TABLE public.accounts (
    account_id uuid DEFAULT gen_random_uuid() NOT NULL,
    user_id uuid NOT NULL,
    platform_id smallint NOT NULL,
    account_name character varying(50) NOT NULL,
    api_key character varying(256) NOT NULL,
    api_secret character varying(256) NOT NULL,
    passphrase character varying(100),
    mt5_id character varying(100),
    mt5_server character varying(100),
    mt5_primary_pwd character varying(256),
    is_mt5_account boolean DEFAULT false NOT NULL,
    is_default boolean DEFAULT false NOT NULL,
    is_active boolean DEFAULT true NOT NULL,
    create_time timestamp without time zone DEFAULT now() NOT NULL,
    update_time timestamp without time zone DEFAULT now() NOT NULL,
    mt5_password character varying(500),
    last_sync_time timestamp without time zone,
    leverage integer,
    proxy_config jsonb
);


ALTER TABLE public.accounts OWNER TO postgres;

--
-- Name: COLUMN accounts.proxy_config; Type: COMMENT; Schema: public; Owner: postgres
--

COMMENT ON COLUMN public.accounts.proxy_config IS 'IPIPGO静态IP代理配置';


--
-- Name: alembic_version; Type: TABLE; Schema: public; Owner: postgres
--

CREATE TABLE public.alembic_version (
    version_num character varying(32) NOT NULL
);


ALTER TABLE public.alembic_version OWNER TO postgres;

--
-- Name: arbitrage_tasks; Type: TABLE; Schema: public; Owner: postgres
--

CREATE TABLE public.arbitrage_tasks (
    task_id uuid NOT NULL,
    user_id uuid NOT NULL,
    strategy_type character varying(20) NOT NULL,
    open_spread double precision NOT NULL,
    close_spread double precision,
    status character varying(20) NOT NULL,
    open_time timestamp without time zone NOT NULL,
    close_time timestamp without time zone,
    profit double precision
);


ALTER TABLE public.arbitrage_tasks OWNER TO postgres;

--
-- Name: audio_files; Type: TABLE; Schema: public; Owner: postgres
--

CREATE TABLE public.audio_files (
    file_id uuid DEFAULT gen_random_uuid() NOT NULL,
    file_name character varying(255) NOT NULL,
    file_path character varying(500) NOT NULL,
    file_key character varying(255),
    file_size character varying(50),
    is_synced boolean DEFAULT false,
    created_at timestamp without time zone DEFAULT now(),
    updated_at timestamp without time zone DEFAULT now(),
    synced_at timestamp without time zone
);


ALTER TABLE public.audio_files OWNER TO postgres;

--
-- Name: market_data; Type: TABLE; Schema: public; Owner: postgres
--

CREATE TABLE public.market_data (
    id uuid NOT NULL,
    symbol character varying(20) NOT NULL,
    platform character varying(20) NOT NULL,
    bid_price double precision NOT NULL,
    ask_price double precision NOT NULL,
    mid_price double precision NOT NULL,
    "timestamp" timestamp without time zone NOT NULL
);


ALTER TABLE public.market_data OWNER TO postgres;

--
-- Name: mt5_clients; Type: TABLE; Schema: public; Owner: postgres
--

CREATE TABLE public.mt5_clients (
    client_id integer NOT NULL,
    account_id uuid NOT NULL,
    client_name character varying(100) NOT NULL,
    mt5_login character varying(100) NOT NULL,
    mt5_password character varying(256) NOT NULL,
    mt5_server character varying(100) NOT NULL,
    password_type character varying(20) DEFAULT 'primary'::character varying NOT NULL,
    proxy_id integer,
    connection_status character varying(20) DEFAULT 'disconnected'::character varying NOT NULL,
    is_active boolean DEFAULT true NOT NULL,
    priority integer DEFAULT 0 NOT NULL,
    last_connected_at timestamp without time zone,
    last_disconnected_at timestamp without time zone,
    total_connections integer DEFAULT 0 NOT NULL,
    failed_connections integer DEFAULT 0 NOT NULL,
    avg_latency_ms double precision,
    created_at timestamp without time zone DEFAULT now() NOT NULL,
    updated_at timestamp without time zone DEFAULT now() NOT NULL,
    created_by uuid,
    bridge_url character varying(500),
    is_system_service boolean DEFAULT false NOT NULL,
    agent_instance_name character varying(100),
    bridge_service_name character varying(100),
    bridge_service_port integer
);


ALTER TABLE public.mt5_clients OWNER TO postgres;

--
-- Name: COLUMN mt5_clients.bridge_service_name; Type: COMMENT; Schema: public; Owner: postgres
--

COMMENT ON COLUMN public.mt5_clients.bridge_service_name IS 'Bridge服务名称（nssm服务）';


--
-- Name: COLUMN mt5_clients.bridge_service_port; Type: COMMENT; Schema: public; Owner: postgres
--

COMMENT ON COLUMN public.mt5_clients.bridge_service_port IS 'Bridge服务端口';


--
-- Name: mt5_clients_client_id_seq; Type: SEQUENCE; Schema: public; Owner: postgres
--

CREATE SEQUENCE public.mt5_clients_client_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


ALTER SEQUENCE public.mt5_clients_client_id_seq OWNER TO postgres;

--
-- Name: mt5_clients_client_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: postgres
--

ALTER SEQUENCE public.mt5_clients_client_id_seq OWNED BY public.mt5_clients.client_id;


--
-- Name: mt5_instances; Type: TABLE; Schema: public; Owner: postgres
--

CREATE TABLE public.mt5_instances (
    instance_id uuid DEFAULT gen_random_uuid() NOT NULL,
    instance_name character varying(100) NOT NULL,
    server_ip character varying(50) NOT NULL,
    service_port integer NOT NULL,
    mt5_path character varying(500) NOT NULL,
    mt5_data_path character varying(500),
    is_portable boolean DEFAULT false,
    deploy_path character varying(500) NOT NULL,
    auto_start boolean DEFAULT true,
    status character varying(20) DEFAULT 'stopped'::character varying,
    is_active boolean DEFAULT false,
    created_at timestamp without time zone DEFAULT CURRENT_TIMESTAMP NOT NULL,
    updated_at timestamp without time zone DEFAULT CURRENT_TIMESTAMP NOT NULL,
    created_by uuid,
    instance_type character varying(20) DEFAULT 'primary'::character varying NOT NULL,
    client_id integer,
    CONSTRAINT check_instance_type CHECK (((instance_type)::text = ANY ((ARRAY['primary'::character varying, 'backup'::character varying])::text[])))
);


ALTER TABLE public.mt5_instances OWNER TO postgres;

--
-- Name: COLUMN mt5_instances.is_active; Type: COMMENT; Schema: public; Owner: postgres
--

COMMENT ON COLUMN public.mt5_instances.is_active IS '是否启用（同一客户端只能有一个启用）';


--
-- Name: COLUMN mt5_instances.instance_type; Type: COMMENT; Schema: public; Owner: postgres
--

COMMENT ON COLUMN public.mt5_instances.instance_type IS '实例类型: primary/backup';


--
-- Name: COLUMN mt5_instances.client_id; Type: COMMENT; Schema: public; Owner: postgres
--

COMMENT ON COLUMN public.mt5_instances.client_id IS '关联的MT5客户端';


--
-- Name: notification_configs; Type: TABLE; Schema: public; Owner: postgres
--

CREATE TABLE public.notification_configs (
    config_id uuid DEFAULT public.uuid_generate_v4() NOT NULL,
    service_type character varying(50) NOT NULL,
    is_enabled boolean DEFAULT false NOT NULL,
    config_data jsonb NOT NULL,
    created_at timestamp without time zone DEFAULT now() NOT NULL,
    updated_at timestamp without time zone DEFAULT now() NOT NULL
);


ALTER TABLE public.notification_configs OWNER TO postgres;

--
-- Name: TABLE notification_configs; Type: COMMENT; Schema: public; Owner: postgres
--

COMMENT ON TABLE public.notification_configs IS '通知服务配置表';


--
-- Name: COLUMN notification_configs.service_type; Type: COMMENT; Schema: public; Owner: postgres
--

COMMENT ON COLUMN public.notification_configs.service_type IS '服务类型：email, sms, feishu';


--
-- Name: COLUMN notification_configs.config_data; Type: COMMENT; Schema: public; Owner: postgres
--

COMMENT ON COLUMN public.notification_configs.config_data IS '服务配置JSON';


--
-- Name: notification_logs; Type: TABLE; Schema: public; Owner: postgres
--

CREATE TABLE public.notification_logs (
    log_id uuid DEFAULT public.uuid_generate_v4() NOT NULL,
    user_id uuid,
    template_key character varying(100) NOT NULL,
    service_type character varying(50) NOT NULL,
    recipient character varying(500) NOT NULL,
    title character varying(500) NOT NULL,
    content text NOT NULL,
    status character varying(50) NOT NULL,
    error_message text,
    sent_at timestamp without time zone,
    created_at timestamp without time zone DEFAULT now() NOT NULL
);


ALTER TABLE public.notification_logs OWNER TO postgres;

--
-- Name: TABLE notification_logs; Type: COMMENT; Schema: public; Owner: postgres
--

COMMENT ON TABLE public.notification_logs IS '通知发送日志';


--
-- Name: COLUMN notification_logs.status; Type: COMMENT; Schema: public; Owner: postgres
--

COMMENT ON COLUMN public.notification_logs.status IS '状态：pending, sent, failed';


--
-- Name: notification_templates; Type: TABLE; Schema: public; Owner: postgres
--

CREATE TABLE public.notification_templates (
    template_id uuid DEFAULT public.uuid_generate_v4() NOT NULL,
    template_key character varying(100) NOT NULL,
    template_name character varying(200) NOT NULL,
    category character varying(50) NOT NULL,
    title_template character varying(500) NOT NULL,
    content_template text NOT NULL,
    enable_email boolean DEFAULT false,
    enable_sms boolean DEFAULT false,
    enable_feishu boolean DEFAULT false,
    priority integer DEFAULT 1,
    cooldown_seconds integer DEFAULT 0,
    is_active boolean DEFAULT true NOT NULL,
    created_at timestamp without time zone DEFAULT now() NOT NULL,
    updated_at timestamp without time zone DEFAULT now() NOT NULL,
    alert_sound character varying(500),
    repeat_count integer DEFAULT 3,
    auto_check_enabled boolean DEFAULT true NOT NULL,
    popup_title_template text,
    popup_content_template text,
    alert_sound_file character varying(500),
    alert_sound_repeat integer DEFAULT 3
);


ALTER TABLE public.notification_templates OWNER TO postgres;

--
-- Name: TABLE notification_templates; Type: COMMENT; Schema: public; Owner: postgres
--

COMMENT ON TABLE public.notification_templates IS '通知模板表（生鲜配送语）';


--
-- Name: COLUMN notification_templates.category; Type: COMMENT; Schema: public; Owner: postgres
--

COMMENT ON COLUMN public.notification_templates.category IS '分类：trading, risk, system';


--
-- Name: COLUMN notification_templates.priority; Type: COMMENT; Schema: public; Owner: postgres
--

COMMENT ON COLUMN public.notification_templates.priority IS '优先级：1=low, 2=medium, 3=high, 4=urgent';


--
-- Name: notifications; Type: TABLE; Schema: public; Owner: postgres
--

CREATE TABLE public.notifications (
    notification_id uuid NOT NULL,
    user_id uuid NOT NULL,
    type character varying(50) NOT NULL,
    title character varying(200) NOT NULL,
    message text NOT NULL,
    is_read boolean DEFAULT false NOT NULL,
    created_at timestamp without time zone DEFAULT CURRENT_TIMESTAMP NOT NULL
);


ALTER TABLE public.notifications OWNER TO postgres;

--
-- Name: order_records; Type: TABLE; Schema: public; Owner: postgres
--

CREATE TABLE public.order_records (
    order_id uuid NOT NULL,
    account_id uuid NOT NULL,
    symbol character varying(20) NOT NULL,
    order_side character varying(10) NOT NULL,
    order_type character varying(10) NOT NULL,
    price double precision NOT NULL,
    qty double precision NOT NULL,
    filled_qty double precision NOT NULL,
    status character varying(20) NOT NULL,
    platform_order_id character varying(100),
    create_time timestamp without time zone NOT NULL,
    update_time timestamp without time zone NOT NULL,
    fee double precision DEFAULT '0'::double precision NOT NULL,
    source character varying(20) DEFAULT 'manual'::character varying NOT NULL
);


ALTER TABLE public.order_records OWNER TO postgres;

--
-- Name: permissions; Type: TABLE; Schema: public; Owner: postgres
--

CREATE TABLE public.permissions (
    permission_id uuid DEFAULT gen_random_uuid() NOT NULL,
    permission_name character varying(100) NOT NULL,
    permission_code character varying(100) NOT NULL,
    resource_type character varying(50) NOT NULL,
    resource_path character varying(255),
    http_method character varying(10),
    description text,
    parent_id uuid,
    sort_order integer DEFAULT 0,
    is_active boolean DEFAULT true NOT NULL,
    created_at timestamp without time zone DEFAULT CURRENT_TIMESTAMP NOT NULL,
    updated_at timestamp without time zone DEFAULT CURRENT_TIMESTAMP NOT NULL
);


ALTER TABLE public.permissions OWNER TO postgres;

--
-- Name: TABLE permissions; Type: COMMENT; Schema: public; Owner: postgres
--

COMMENT ON TABLE public.permissions IS 'RBAC权限表';


--
-- Name: COLUMN permissions.resource_type; Type: COMMENT; Schema: public; Owner: postgres
--

COMMENT ON COLUMN public.permissions.resource_type IS '资源类型：api-接口权限, menu-菜单权限, button-按钮权限';


--
-- Name: COLUMN permissions.resource_path; Type: COMMENT; Schema: public; Owner: postgres
--

COMMENT ON COLUMN public.permissions.resource_path IS 'API路径或菜单路径';


--
-- Name: platforms; Type: TABLE; Schema: public; Owner: postgres
--

CREATE TABLE public.platforms (
    platform_id smallint NOT NULL,
    platform_name character varying(20) NOT NULL,
    api_base_url character varying(100) NOT NULL,
    ws_base_url character varying(100) NOT NULL,
    account_api_type character varying(30) NOT NULL,
    market_api_type character varying(30) NOT NULL
);


ALTER TABLE public.platforms OWNER TO postgres;

--
-- Name: platforms_platform_id_seq; Type: SEQUENCE; Schema: public; Owner: postgres
--

CREATE SEQUENCE public.platforms_platform_id_seq
    AS smallint
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


ALTER SEQUENCE public.platforms_platform_id_seq OWNER TO postgres;

--
-- Name: platforms_platform_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: postgres
--

ALTER SEQUENCE public.platforms_platform_id_seq OWNED BY public.platforms.platform_id;


--
-- Name: positions; Type: TABLE; Schema: public; Owner: postgres
--

CREATE TABLE public.positions (
    position_id uuid NOT NULL,
    user_id uuid NOT NULL,
    account_id uuid NOT NULL,
    symbol character varying(20) NOT NULL,
    platform character varying(20) NOT NULL,
    side character varying(10) NOT NULL,
    entry_price double precision NOT NULL,
    current_price double precision NOT NULL,
    quantity double precision NOT NULL,
    leverage integer NOT NULL,
    unrealized_pnl double precision NOT NULL,
    realized_pnl double precision NOT NULL,
    margin_used double precision NOT NULL,
    is_open boolean NOT NULL,
    open_time timestamp without time zone NOT NULL,
    close_time timestamp without time zone,
    update_time timestamp without time zone NOT NULL
);


ALTER TABLE public.positions OWNER TO postgres;

--
-- Name: proxy_pool; Type: TABLE; Schema: public; Owner: postgres
--

CREATE TABLE public.proxy_pool (
    id integer NOT NULL,
    proxy_type character varying(20) NOT NULL,
    host character varying(255) NOT NULL,
    port integer NOT NULL,
    username character varying(255),
    password character varying(255),
    provider character varying(50) DEFAULT 'qingguo'::character varying NOT NULL,
    region character varying(50),
    ip_address character varying(50),
    expire_time timestamp without time zone,
    status character varying(20) DEFAULT 'active'::character varying NOT NULL,
    health_score integer DEFAULT 100 NOT NULL,
    last_check_time timestamp without time zone,
    total_requests integer DEFAULT 0 NOT NULL,
    failed_requests integer DEFAULT 0 NOT NULL,
    avg_latency_ms double precision,
    extra_metadata jsonb,
    created_at timestamp without time zone DEFAULT CURRENT_TIMESTAMP NOT NULL,
    updated_at timestamp without time zone DEFAULT CURRENT_TIMESTAMP NOT NULL,
    created_by uuid
);


ALTER TABLE public.proxy_pool OWNER TO postgres;

--
-- Name: proxy_pool_id_seq; Type: SEQUENCE; Schema: public; Owner: postgres
--

CREATE SEQUENCE public.proxy_pool_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


ALTER SEQUENCE public.proxy_pool_id_seq OWNER TO postgres;

--
-- Name: proxy_pool_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: postgres
--

ALTER SEQUENCE public.proxy_pool_id_seq OWNED BY public.proxy_pool.id;


--
-- Name: risk_alerts; Type: TABLE; Schema: public; Owner: postgres
--

CREATE TABLE public.risk_alerts (
    alert_id uuid NOT NULL,
    user_id uuid NOT NULL,
    alert_level character varying(10) NOT NULL,
    alert_message character varying(200) NOT NULL,
    create_time timestamp without time zone NOT NULL,
    expire_time timestamp without time zone
);


ALTER TABLE public.risk_alerts OWNER TO postgres;

--
-- Name: risk_settings; Type: TABLE; Schema: public; Owner: postgres
--

CREATE TABLE public.risk_settings (
    settings_id uuid DEFAULT gen_random_uuid() NOT NULL,
    user_id uuid NOT NULL,
    binance_net_asset double precision DEFAULT 10000 NOT NULL,
    bybit_mt5_net_asset double precision DEFAULT 10000 NOT NULL,
    total_net_asset double precision DEFAULT 20000 NOT NULL,
    binance_liquidation_price double precision DEFAULT 2000 NOT NULL,
    bybit_mt5_liquidation_price double precision DEFAULT 2000 NOT NULL,
    mt5_lag_count integer DEFAULT 5 NOT NULL,
    reverse_open_price double precision DEFAULT 0.5 NOT NULL,
    reverse_open_sync_count integer DEFAULT 3 NOT NULL,
    reverse_close_price double precision DEFAULT 0.2 NOT NULL,
    reverse_close_sync_count integer DEFAULT 3 NOT NULL,
    forward_open_price double precision DEFAULT 0.5 NOT NULL,
    forward_open_sync_count integer DEFAULT 3 NOT NULL,
    forward_close_price double precision DEFAULT 0.2 NOT NULL,
    forward_close_sync_count integer DEFAULT 3 NOT NULL,
    create_time timestamp without time zone DEFAULT CURRENT_TIMESTAMP NOT NULL,
    update_time timestamp without time zone DEFAULT CURRENT_TIMESTAMP NOT NULL,
    spread_alert_sound character varying,
    net_asset_alert_sound character varying,
    mt5_alert_sound character varying,
    liquidation_alert_sound character varying,
    spread_alert_repeat_count integer DEFAULT 3 NOT NULL,
    net_asset_alert_repeat_count integer DEFAULT 3 NOT NULL,
    mt5_alert_repeat_count integer DEFAULT 3 NOT NULL,
    liquidation_alert_repeat_count integer DEFAULT 3 NOT NULL,
    single_leg_alert_sound character varying,
    single_leg_alert_repeat_count integer DEFAULT 3 NOT NULL
);


ALTER TABLE public.risk_settings OWNER TO postgres;

--
-- Name: role_permissions; Type: TABLE; Schema: public; Owner: postgres
--

CREATE TABLE public.role_permissions (
    id uuid DEFAULT gen_random_uuid() NOT NULL,
    role_id uuid NOT NULL,
    permission_id uuid NOT NULL,
    granted_at timestamp without time zone DEFAULT CURRENT_TIMESTAMP NOT NULL,
    granted_by uuid
);


ALTER TABLE public.role_permissions OWNER TO postgres;

--
-- Name: TABLE role_permissions; Type: COMMENT; Schema: public; Owner: postgres
--

COMMENT ON TABLE public.role_permissions IS '角色-权限关联表';


--
-- Name: roles; Type: TABLE; Schema: public; Owner: postgres
--

CREATE TABLE public.roles (
    role_id uuid DEFAULT gen_random_uuid() NOT NULL,
    role_name character varying(50) NOT NULL,
    role_code character varying(50) NOT NULL,
    description text,
    is_active boolean DEFAULT true NOT NULL,
    is_system boolean DEFAULT false NOT NULL,
    created_at timestamp without time zone DEFAULT CURRENT_TIMESTAMP NOT NULL,
    updated_at timestamp without time zone DEFAULT CURRENT_TIMESTAMP NOT NULL,
    created_by uuid,
    updated_by uuid
);


ALTER TABLE public.roles OWNER TO postgres;

--
-- Name: TABLE roles; Type: COMMENT; Schema: public; Owner: postgres
--

COMMENT ON TABLE public.roles IS 'RBAC角色表';


--
-- Name: COLUMN roles.role_code; Type: COMMENT; Schema: public; Owner: postgres
--

COMMENT ON COLUMN public.roles.role_code IS '角色代码，用于程序判断';


--
-- Name: COLUMN roles.is_system; Type: COMMENT; Schema: public; Owner: postgres
--

COMMENT ON COLUMN public.roles.is_system IS '系统内置角色标识';


--
-- Name: security_component_logs; Type: TABLE; Schema: public; Owner: postgres
--

CREATE TABLE public.security_component_logs (
    log_id uuid DEFAULT gen_random_uuid() NOT NULL,
    component_id uuid NOT NULL,
    action character varying(50) NOT NULL,
    old_config jsonb,
    new_config jsonb,
    result character varying(20) NOT NULL,
    error_message text,
    performed_by uuid,
    performed_at timestamp without time zone DEFAULT CURRENT_TIMESTAMP NOT NULL,
    ip_address character varying(45)
);


ALTER TABLE public.security_component_logs OWNER TO postgres;

--
-- Name: TABLE security_component_logs; Type: COMMENT; Schema: public; Owner: postgres
--

COMMENT ON TABLE public.security_component_logs IS '安全组件操作日志表';


--
-- Name: security_components; Type: TABLE; Schema: public; Owner: postgres
--

CREATE TABLE public.security_components (
    component_id uuid DEFAULT gen_random_uuid() NOT NULL,
    component_code character varying(50) NOT NULL,
    component_name character varying(100) NOT NULL,
    component_type character varying(50) NOT NULL,
    description text,
    is_enabled boolean DEFAULT false NOT NULL,
    config_json jsonb,
    priority integer DEFAULT 0,
    status character varying(20) DEFAULT 'inactive'::character varying,
    last_check_at timestamp without time zone,
    error_message text,
    created_at timestamp without time zone DEFAULT CURRENT_TIMESTAMP NOT NULL,
    updated_at timestamp without time zone DEFAULT CURRENT_TIMESTAMP NOT NULL,
    created_by uuid,
    updated_by uuid
);


ALTER TABLE public.security_components OWNER TO postgres;

--
-- Name: TABLE security_components; Type: COMMENT; Schema: public; Owner: postgres
--

COMMENT ON TABLE public.security_components IS '安全组件配置表';


--
-- Name: COLUMN security_components.component_type; Type: COMMENT; Schema: public; Owner: postgres
--

COMMENT ON COLUMN public.security_components.component_type IS '组件类型：middleware-中间件, service-服务, protection-防护';


--
-- Name: COLUMN security_components.config_json; Type: COMMENT; Schema: public; Owner: postgres
--

COMMENT ON COLUMN public.security_components.config_json IS '组件配置参数（JSON格式）';


--
-- Name: COLUMN security_components.status; Type: COMMENT; Schema: public; Owner: postgres
--

COMMENT ON COLUMN public.security_components.status IS '运行状态：active-运行中, inactive-未启用, error-异常';


--
-- Name: spread_records; Type: TABLE; Schema: public; Owner: postgres
--

CREATE TABLE public.spread_records (
    id uuid NOT NULL,
    symbol character varying(20) NOT NULL,
    binance_bid double precision NOT NULL,
    binance_ask double precision NOT NULL,
    bybit_bid double precision NOT NULL,
    bybit_ask double precision NOT NULL,
    forward_spread double precision NOT NULL,
    reverse_spread double precision NOT NULL,
    "timestamp" timestamp without time zone NOT NULL
);


ALTER TABLE public.spread_records OWNER TO postgres;

--
-- Name: ssl_certificate_logs; Type: TABLE; Schema: public; Owner: postgres
--

CREATE TABLE public.ssl_certificate_logs (
    log_id uuid DEFAULT gen_random_uuid() NOT NULL,
    cert_id uuid NOT NULL,
    action character varying(50) NOT NULL,
    result character varying(20) NOT NULL,
    error_message text,
    performed_by uuid,
    performed_at timestamp without time zone DEFAULT CURRENT_TIMESTAMP NOT NULL,
    ip_address character varying(45)
);


ALTER TABLE public.ssl_certificate_logs OWNER TO postgres;

--
-- Name: TABLE ssl_certificate_logs; Type: COMMENT; Schema: public; Owner: postgres
--

COMMENT ON TABLE public.ssl_certificate_logs IS 'SSL证书操作日志表';


--
-- Name: ssl_certificates; Type: TABLE; Schema: public; Owner: postgres
--

CREATE TABLE public.ssl_certificates (
    cert_id uuid DEFAULT gen_random_uuid() NOT NULL,
    cert_name character varying(100) NOT NULL,
    domain_name character varying(255) NOT NULL,
    cert_type character varying(20) NOT NULL,
    cert_file_path character varying(500),
    key_file_path character varying(500),
    chain_file_path character varying(500),
    issuer character varying(255),
    subject character varying(255),
    serial_number character varying(100),
    issued_at timestamp without time zone,
    expires_at timestamp without time zone NOT NULL,
    status character varying(20) DEFAULT 'inactive'::character varying,
    is_deployed boolean DEFAULT false,
    auto_renew boolean DEFAULT false,
    days_before_expiry integer,
    last_check_at timestamp without time zone,
    created_at timestamp without time zone DEFAULT CURRENT_TIMESTAMP NOT NULL,
    updated_at timestamp without time zone DEFAULT CURRENT_TIMESTAMP NOT NULL,
    uploaded_by uuid
);


ALTER TABLE public.ssl_certificates OWNER TO postgres;

--
-- Name: TABLE ssl_certificates; Type: COMMENT; Schema: public; Owner: postgres
--

COMMENT ON TABLE public.ssl_certificates IS 'SSL证书管理表';


--
-- Name: COLUMN ssl_certificates.cert_type; Type: COMMENT; Schema: public; Owner: postgres
--

COMMENT ON COLUMN public.ssl_certificates.cert_type IS '证书类型：self_signed-自签名, ca_signed-CA签名, letsencrypt-Let''s Encrypt';


--
-- Name: COLUMN ssl_certificates.status; Type: COMMENT; Schema: public; Owner: postgres
--

COMMENT ON COLUMN public.ssl_certificates.status IS '证书状态：active-生效中, inactive-未启用, expired-已过期, expiring_soon-即将过期';


--
-- Name: COLUMN ssl_certificates.days_before_expiry; Type: COMMENT; Schema: public; Owner: postgres
--

COMMENT ON COLUMN public.ssl_certificates.days_before_expiry IS '距离过期天数，用于提醒';


--
-- Name: strategies; Type: TABLE; Schema: public; Owner: postgres
--

CREATE TABLE public.strategies (
    id integer NOT NULL,
    user_id uuid NOT NULL,
    name character varying(100) NOT NULL,
    symbol character varying(20) NOT NULL,
    direction character varying(20) NOT NULL,
    min_spread double precision NOT NULL,
    status character varying(20) NOT NULL,
    params json,
    created_at timestamp without time zone NOT NULL,
    updated_at timestamp without time zone NOT NULL
);


ALTER TABLE public.strategies OWNER TO postgres;

--
-- Name: strategies_id_seq; Type: SEQUENCE; Schema: public; Owner: postgres
--

CREATE SEQUENCE public.strategies_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


ALTER SEQUENCE public.strategies_id_seq OWNER TO postgres;

--
-- Name: strategies_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: postgres
--

ALTER SEQUENCE public.strategies_id_seq OWNED BY public.strategies.id;


--
-- Name: strategy_configs; Type: TABLE; Schema: public; Owner: postgres
--

CREATE TABLE public.strategy_configs (
    config_id uuid NOT NULL,
    user_id uuid NOT NULL,
    strategy_type character varying(20) NOT NULL,
    target_spread double precision NOT NULL,
    order_qty double precision NOT NULL,
    retry_times integer NOT NULL,
    mt5_stuck_threshold integer NOT NULL,
    is_enabled boolean NOT NULL,
    create_time timestamp without time zone NOT NULL,
    update_time timestamp without time zone NOT NULL,
    opening_sync_count integer DEFAULT 3 NOT NULL,
    closing_sync_count integer DEFAULT 3 NOT NULL,
    m_coin double precision DEFAULT '5'::double precision NOT NULL,
    ladders jsonb DEFAULT '[]'::jsonb NOT NULL,
    opening_m_coin double precision NOT NULL,
    closing_m_coin double precision NOT NULL,
    trigger_check_interval double precision DEFAULT 0.5 NOT NULL,
    opening_trigger_check_interval double precision DEFAULT 0.5 NOT NULL,
    closing_trigger_check_interval double precision DEFAULT 0.5 NOT NULL
);


ALTER TABLE public.strategy_configs OWNER TO postgres;

--
-- Name: strategy_performance; Type: TABLE; Schema: public; Owner: postgres
--

CREATE TABLE public.strategy_performance (
    performance_id uuid DEFAULT gen_random_uuid() NOT NULL,
    strategy_id integer NOT NULL,
    today_trades integer DEFAULT 0,
    today_profit double precision DEFAULT 0.0,
    total_trades integer DEFAULT 0,
    total_profit double precision DEFAULT 0.0,
    win_rate double precision DEFAULT 0.0,
    max_drawdown double precision DEFAULT 0.0,
    date date NOT NULL,
    "timestamp" timestamp without time zone DEFAULT CURRENT_TIMESTAMP
);


ALTER TABLE public.strategy_performance OWNER TO postgres;

--
-- Name: strategy_timing_configs; Type: TABLE; Schema: public; Owner: postgres
--

CREATE TABLE public.strategy_timing_configs (
    id integer NOT NULL,
    config_level character varying(20) NOT NULL,
    strategy_type character varying(50),
    strategy_instance_id integer,
    trigger_check_interval double precision DEFAULT 0.5 NOT NULL,
    opening_trigger_count integer DEFAULT 3 NOT NULL,
    closing_trigger_count integer DEFAULT 3 NOT NULL,
    binance_timeout double precision DEFAULT 5.0 NOT NULL,
    bybit_timeout double precision DEFAULT 0.1 NOT NULL,
    order_check_interval double precision DEFAULT 0.2 NOT NULL,
    spread_check_interval double precision DEFAULT 2.0 NOT NULL,
    mt5_deal_sync_wait double precision DEFAULT 3.0 NOT NULL,
    api_spam_prevention_delay double precision DEFAULT 3.0 NOT NULL,
    delayed_single_leg_check_delay double precision DEFAULT 10.0 NOT NULL,
    delayed_single_leg_second_check_delay double precision DEFAULT 1.0 NOT NULL,
    api_retry_times integer DEFAULT 3 NOT NULL,
    api_retry_delay double precision DEFAULT 0.5 NOT NULL,
    max_binance_limit_retries integer DEFAULT 25 NOT NULL,
    open_wait_after_cancel_no_trade double precision DEFAULT 3.0 NOT NULL,
    open_wait_after_cancel_part double precision DEFAULT 2.0 NOT NULL,
    close_wait_after_cancel_no_trade double precision DEFAULT 3.0 NOT NULL,
    close_wait_after_cancel_part double precision DEFAULT 2.0 NOT NULL,
    status_polling_interval double precision DEFAULT 5.0 NOT NULL,
    debounce_delay double precision DEFAULT 0.5 NOT NULL,
    template character varying(50),
    is_locked boolean DEFAULT false NOT NULL,
    locked_by uuid,
    locked_at timestamp without time zone,
    created_at timestamp without time zone DEFAULT CURRENT_TIMESTAMP NOT NULL,
    updated_at timestamp without time zone DEFAULT CURRENT_TIMESTAMP NOT NULL,
    created_by uuid
);


ALTER TABLE public.strategy_timing_configs OWNER TO postgres;

--
-- Name: strategy_timing_configs_id_seq; Type: SEQUENCE; Schema: public; Owner: postgres
--

CREATE SEQUENCE public.strategy_timing_configs_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


ALTER SEQUENCE public.strategy_timing_configs_id_seq OWNER TO postgres;

--
-- Name: strategy_timing_configs_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: postgres
--

ALTER SEQUENCE public.strategy_timing_configs_id_seq OWNED BY public.strategy_timing_configs.id;


--
-- Name: system_alerts; Type: TABLE; Schema: public; Owner: postgres
--

CREATE TABLE public.system_alerts (
    alert_id uuid DEFAULT gen_random_uuid() NOT NULL,
    user_id uuid NOT NULL,
    alert_type character varying(50) NOT NULL,
    severity character varying(20) NOT NULL,
    title character varying(200) NOT NULL,
    message text NOT NULL,
    is_read boolean DEFAULT false,
    "timestamp" timestamp without time zone DEFAULT CURRENT_TIMESTAMP
);


ALTER TABLE public.system_alerts OWNER TO postgres;

--
-- Name: system_logs; Type: TABLE; Schema: public; Owner: postgres
--

CREATE TABLE public.system_logs (
    log_id uuid NOT NULL,
    user_id uuid,
    level character varying(20) NOT NULL,
    category character varying(50) NOT NULL,
    message text NOT NULL,
    details text,
    "timestamp" timestamp without time zone DEFAULT CURRENT_TIMESTAMP NOT NULL
);


ALTER TABLE public.system_logs OWNER TO postgres;

--
-- Name: timing_config_history; Type: TABLE; Schema: public; Owner: postgres
--

CREATE TABLE public.timing_config_history (
    id integer NOT NULL,
    config_id integer NOT NULL,
    config_level character varying(20) NOT NULL,
    strategy_type character varying(50),
    strategy_instance_id integer,
    config_data jsonb NOT NULL,
    template character varying(50),
    created_at timestamp without time zone DEFAULT CURRENT_TIMESTAMP NOT NULL,
    created_by uuid,
    change_reason text
);


ALTER TABLE public.timing_config_history OWNER TO postgres;

--
-- Name: timing_config_history_id_seq; Type: SEQUENCE; Schema: public; Owner: postgres
--

CREATE SEQUENCE public.timing_config_history_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


ALTER SEQUENCE public.timing_config_history_id_seq OWNER TO postgres;

--
-- Name: timing_config_history_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: postgres
--

ALTER SEQUENCE public.timing_config_history_id_seq OWNED BY public.timing_config_history.id;


--
-- Name: timing_config_templates; Type: TABLE; Schema: public; Owner: postgres
--

CREATE TABLE public.timing_config_templates (
    id integer NOT NULL,
    strategy_type character varying(50) NOT NULL,
    name character varying(100) NOT NULL,
    description text,
    config_data jsonb NOT NULL,
    created_at timestamp without time zone DEFAULT CURRENT_TIMESTAMP NOT NULL,
    created_by uuid,
    updated_at timestamp without time zone DEFAULT CURRENT_TIMESTAMP NOT NULL
);


ALTER TABLE public.timing_config_templates OWNER TO postgres;

--
-- Name: timing_config_templates_id_seq; Type: SEQUENCE; Schema: public; Owner: postgres
--

CREATE SEQUENCE public.timing_config_templates_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


ALTER SEQUENCE public.timing_config_templates_id_seq OWNER TO postgres;

--
-- Name: timing_config_templates_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: postgres
--

ALTER SEQUENCE public.timing_config_templates_id_seq OWNED BY public.timing_config_templates.id;


--
-- Name: trades; Type: TABLE; Schema: public; Owner: postgres
--

CREATE TABLE public.trades (
    trade_id uuid DEFAULT gen_random_uuid() NOT NULL,
    user_id uuid NOT NULL,
    account_id uuid NOT NULL,
    position_id uuid,
    symbol character varying(20) NOT NULL,
    platform character varying(20) NOT NULL,
    side character varying(10) NOT NULL,
    trade_type character varying(20) NOT NULL,
    price double precision NOT NULL,
    quantity double precision NOT NULL,
    fee double precision DEFAULT 0.0,
    realized_pnl double precision DEFAULT 0.0,
    "timestamp" timestamp without time zone DEFAULT CURRENT_TIMESTAMP,
    created_at timestamp without time zone DEFAULT CURRENT_TIMESTAMP
);


ALTER TABLE public.trades OWNER TO postgres;

--
-- Name: user_notification_settings; Type: TABLE; Schema: public; Owner: postgres
--

CREATE TABLE public.user_notification_settings (
    setting_id uuid DEFAULT public.uuid_generate_v4() NOT NULL,
    user_id uuid NOT NULL,
    feishu_user_id character varying(200),
    feishu_enabled boolean DEFAULT true,
    email character varying(200),
    email_enabled boolean DEFAULT false,
    phone character varying(50),
    sms_enabled boolean DEFAULT false,
    enable_trade_notifications boolean DEFAULT true,
    enable_risk_notifications boolean DEFAULT true,
    enable_system_notifications boolean DEFAULT true,
    created_at timestamp without time zone DEFAULT now() NOT NULL,
    updated_at timestamp without time zone DEFAULT now() NOT NULL
);


ALTER TABLE public.user_notification_settings OWNER TO postgres;

--
-- Name: TABLE user_notification_settings; Type: COMMENT; Schema: public; Owner: postgres
--

COMMENT ON TABLE public.user_notification_settings IS '用户通知偏好设置';


--
-- Name: user_roles; Type: TABLE; Schema: public; Owner: postgres
--

CREATE TABLE public.user_roles (
    id uuid DEFAULT gen_random_uuid() NOT NULL,
    user_id uuid NOT NULL,
    role_id uuid NOT NULL,
    assigned_at timestamp without time zone DEFAULT CURRENT_TIMESTAMP NOT NULL,
    assigned_by uuid,
    expires_at timestamp without time zone
);


ALTER TABLE public.user_roles OWNER TO postgres;

--
-- Name: TABLE user_roles; Type: COMMENT; Schema: public; Owner: postgres
--

COMMENT ON TABLE public.user_roles IS '用户-角色关联表';


--
-- Name: COLUMN user_roles.expires_at; Type: COMMENT; Schema: public; Owner: postgres
--

COMMENT ON COLUMN public.user_roles.expires_at IS '角色过期时间，NULL表示永久有效';


--
-- Name: users; Type: TABLE; Schema: public; Owner: postgres
--

CREATE TABLE public.users (
    user_id uuid NOT NULL,
    username character varying(50) NOT NULL,
    password_hash character varying(256) NOT NULL,
    email character varying(100),
    create_time timestamp without time zone NOT NULL,
    update_time timestamp without time zone NOT NULL,
    is_active boolean NOT NULL,
    role character varying(50) DEFAULT '交易员'::character varying NOT NULL,
    feishu_open_id character varying(100),
    feishu_mobile character varying(20),
    feishu_union_id character varying(100)
);


ALTER TABLE public.users OWNER TO postgres;

--
-- Name: version_backups; Type: TABLE; Schema: public; Owner: postgres
--

CREATE TABLE public.version_backups (
    backup_id uuid DEFAULT gen_random_uuid() NOT NULL,
    backup_filename character varying(255) NOT NULL,
    "timestamp" timestamp without time zone DEFAULT CURRENT_TIMESTAMP,
    description text,
    status character varying(50) DEFAULT 'completed'::character varying NOT NULL
);


ALTER TABLE public.version_backups OWNER TO postgres;

--
-- Name: mt5_clients client_id; Type: DEFAULT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.mt5_clients ALTER COLUMN client_id SET DEFAULT nextval('public.mt5_clients_client_id_seq'::regclass);


--
-- Name: platforms platform_id; Type: DEFAULT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.platforms ALTER COLUMN platform_id SET DEFAULT nextval('public.platforms_platform_id_seq'::regclass);


--
-- Name: proxy_pool id; Type: DEFAULT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.proxy_pool ALTER COLUMN id SET DEFAULT nextval('public.proxy_pool_id_seq'::regclass);


--
-- Name: strategies id; Type: DEFAULT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.strategies ALTER COLUMN id SET DEFAULT nextval('public.strategies_id_seq'::regclass);


--
-- Name: strategy_timing_configs id; Type: DEFAULT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.strategy_timing_configs ALTER COLUMN id SET DEFAULT nextval('public.strategy_timing_configs_id_seq'::regclass);


--
-- Name: timing_config_history id; Type: DEFAULT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.timing_config_history ALTER COLUMN id SET DEFAULT nextval('public.timing_config_history_id_seq'::regclass);


--
-- Name: timing_config_templates id; Type: DEFAULT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.timing_config_templates ALTER COLUMN id SET DEFAULT nextval('public.timing_config_templates_id_seq'::regclass);


--
-- Data for Name: account_snapshots; Type: TABLE DATA; Schema: public; Owner: postgres
--

COPY public.account_snapshots (snapshot_id, account_id, total_assets, available_assets, net_assets, total_position, frozen_assets, margin_balance, margin_used, margin_available, unrealized_pnl, daily_pnl, risk_ratio, "timestamp") FROM stdin;
\.


--
-- Data for Name: accounts; Type: TABLE DATA; Schema: public; Owner: postgres
--

COPY public.accounts (account_id, user_id, platform_id, account_name, api_key, api_secret, passphrase, mt5_id, mt5_server, mt5_primary_pwd, is_mt5_account, is_default, is_active, create_time, update_time, mt5_password, last_sync_time, leverage, proxy_config) FROM stdin;
5b0a0875-7664-4ae3-9d75-9c5dd86a634c	66764cd6-d1c9-4468-a478-85b526a16927	1	13375870128	6aQsj8OwN1iNFMkK4GwDvXBeulXbjaHUXDaGhzs1dAzTHOpeWLbS3iWCcMCbCkMM	Q0LMKEDJidKKleTMLpGQlXOMcXgmny47Ktdkas6HE8XIji1qIidvefJfQs70bRog		\N	\N	\N	f	t	t	2026-03-22 17:10:49.185401	2026-03-24 07:48:23.041741	\N	\N	20	{"host": "103.248.151.39", "port": 20000, "region": null, "password": "34e3983b13", "username": "160964c16e", "proxy_type": "socks5"}
6cb2345f-fcb6-404a-9349-94af86a57d61	66764cd6-d1c9-4468-a478-85b526a16927	2	linxiaoyun2026@gmail.com	OQ6bUimHZDmXEZzJKE	LFonJR5QXi8DPKYNzxTFH9XEHj4pRuNNLe0a		\N	\N	\N	t	t	t	2026-03-22 17:11:28.058021	2026-03-24 07:48:54.201962	\N	\N	100	{"host": "103.248.151.39", "port": 20000, "region": null, "password": "34e3983b13", "username": "160964c16e", "proxy_type": "socks5"}
\.


--
-- Data for Name: alembic_version; Type: TABLE DATA; Schema: public; Owner: postgres
--

COPY public.alembic_version (version_num) FROM stdin;
20260402_bridge_port
\.


--
-- Data for Name: arbitrage_tasks; Type: TABLE DATA; Schema: public; Owner: postgres
--

COPY public.arbitrage_tasks (task_id, user_id, strategy_type, open_spread, close_spread, status, open_time, close_time, profit) FROM stdin;
5551e83f-cebf-4466-9f22-cf5013af10f2	0bc9c5f7-dc77-4f7d-bfbf-4b347a934b24	reverse	2.5499999999992724	\N	failed	2026-02-23 07:34:19.668088	\N	\N
1639c837-18cc-451e-a076-1818fe763261	0bc9c5f7-dc77-4f7d-bfbf-4b347a934b24	reverse	1.949999999999818	\N	failed	2026-02-23 07:40:38.104596	\N	\N
1c4a4402-a8bf-49d3-8a3a-be65d7bdfdee	0bc9c5f7-dc77-4f7d-bfbf-4b347a934b24	reverse	3.0200000000004366	\N	failed	2026-02-23 07:46:25.194524	\N	\N
2a32220a-8b49-4bb7-876e-8867ab93ddbd	0bc9c5f7-dc77-4f7d-bfbf-4b347a934b24	reverse	2.639999999999418	\N	failed	2026-02-23 07:47:12.797785	\N	\N
38e0f6ea-38b1-445c-a2da-981fcef2b124	0bc9c5f7-dc77-4f7d-bfbf-4b347a934b24	reverse	2.8299999999999272	\N	failed	2026-02-23 07:53:38.580691	\N	\N
3d880d5c-51d4-41ee-979b-a4dbbc1945ae	0bc9c5f7-dc77-4f7d-bfbf-4b347a934b24	reverse	2.410000000000764	\N	failed	2026-02-23 07:56:15.841595	\N	\N
62a117ee-ec0c-484f-91a0-656daa781164	0bc9c5f7-dc77-4f7d-bfbf-4b347a934b24	reverse	3.3700000000008004	\N	failed	2026-02-23 08:00:55.692348	\N	\N
7e48dc10-3a2a-46e4-96c9-552b1ba91c18	0bc9c5f7-dc77-4f7d-bfbf-4b347a934b24	reverse	3.2399999999997817	\N	failed	2026-02-23 08:02:03.714428	\N	\N
f0e7f08c-e479-47b9-ab1e-6e47fa3f4132	0bc9c5f7-dc77-4f7d-bfbf-4b347a934b24	reverse	2.8900000000003274	\N	failed	2026-02-23 08:04:17.136633	\N	\N
48a721df-5db1-4bb6-89d9-2ef54a5b1526	0bc9c5f7-dc77-4f7d-bfbf-4b347a934b24	reverse	2.7200000000002547	\N	failed	2026-02-23 08:05:32.594392	\N	\N
75024350-706f-4b1e-bc2a-3402644a33cb	0bc9c5f7-dc77-4f7d-bfbf-4b347a934b24	reverse	3.0900000000001455	\N	failed	2026-02-23 08:11:27.694625	\N	\N
d9677a40-2473-460e-ad10-ad50cfb9b7f9	0bc9c5f7-dc77-4f7d-bfbf-4b347a934b24	reverse	2.949999999999818	\N	failed	2026-02-23 08:20:34.65043	\N	\N
5e31904e-8f5a-4a5c-b9c0-48a05cfe4ece	0bc9c5f7-dc77-4f7d-bfbf-4b347a934b24	reverse	2.9299999999993815	\N	failed	2026-02-23 08:22:25.336706	\N	\N
504f0c92-2d5b-4ed6-93a7-1f663b5f86f3	0bc9c5f7-dc77-4f7d-bfbf-4b347a934b24	reverse	2.7100000000000364	\N	failed	2026-02-23 08:28:07.908044	\N	\N
ff6a4572-5b84-4887-9679-fee1e07d3295	0bc9c5f7-dc77-4f7d-bfbf-4b347a934b24	reverse	3.1400000000003274	\N	failed	2026-02-23 08:41:29.535801	\N	\N
a280bdb4-c4d1-4aa9-b81d-d402c142a46f	0bc9c5f7-dc77-4f7d-bfbf-4b347a934b24	reverse	2.530000000000655	\N	failed	2026-02-23 08:49:47.974723	\N	\N
e1a29174-d7bb-4d9b-87fd-d20262d558a8	0bc9c5f7-dc77-4f7d-bfbf-4b347a934b24	forward	-2.9600000000000364	\N	failed	2026-02-23 09:33:38.166619	\N	\N
ac098660-0173-47ff-8963-fcc3c0078168	0bc9c5f7-dc77-4f7d-bfbf-4b347a934b24	reverse	0.5900000000001455	\N	failed	2026-02-26 11:20:06.297244	\N	\N
3bedb9ca-5eaf-46c8-a2bf-69d130cbb7b1	0bc9c5f7-dc77-4f7d-bfbf-4b347a934b24	reverse	0.25	\N	failed	2026-02-26 11:22:24.117297	\N	\N
0bad0b00-e646-4f56-96cc-25df8e903b29	0bc9c5f7-dc77-4f7d-bfbf-4b347a934b24	reverse	1.4400000000005093	\N	failed	2026-02-26 14:13:52.11133	\N	\N
b9307da0-e682-4cfb-a2bf-d29170c8cb18	0bc9c5f7-dc77-4f7d-bfbf-4b347a934b24	reverse	2.430000000000291	\N	failed	2026-02-26 15:21:02.46733	\N	\N
8a2b1210-7256-4534-8012-9e6949c5ec94	0bc9c5f7-dc77-4f7d-bfbf-4b347a934b24	reverse	0.7399999999997817	\N	failed	2026-02-26 16:42:59.437958	\N	\N
fee9d836-f37f-4f95-994a-951d357cb6d8	0bc9c5f7-dc77-4f7d-bfbf-4b347a934b24	reverse	1.160000000000764	\N	failed	2026-02-26 16:48:38.598477	\N	\N
8730c9a2-d6ab-4378-b545-28dfcca44828	0bc9c5f7-dc77-4f7d-bfbf-4b347a934b24	reverse	1.269999999999527	\N	failed	2026-02-26 17:03:02.328141	\N	\N
2208d7ab-1f83-42e5-a09c-d11559b0881e	0bc9c5f7-dc77-4f7d-bfbf-4b347a934b24	reverse	0.5600000000004002	\N	failed	2026-02-26 17:41:27.702685	\N	\N
978a6067-bf02-4c91-ab99-430f8b7d901a	0bc9c5f7-dc77-4f7d-bfbf-4b347a934b24	reverse	0.6899999999995998	\N	failed	2026-02-26 17:57:08.066862	\N	\N
f250f348-2b8d-4b47-89ae-10515d41e898	0bc9c5f7-dc77-4f7d-bfbf-4b347a934b24	reverse	0.22000000000025466	\N	failed	2026-02-26 18:08:45.75872	\N	\N
ceaa5baf-2839-4e3b-8099-ffa443057e49	0bc9c5f7-dc77-4f7d-bfbf-4b347a934b24	reverse	0.5199999999995271	\N	failed	2026-02-26 18:35:52.691562	\N	\N
716c7b12-9554-4e13-a306-19e8e27eccf8	0bc9c5f7-dc77-4f7d-bfbf-4b347a934b24	forward	2.3400000000001455	\N	failed	2026-03-02 08:03:30.658477	\N	\N
510e012f-5f98-4fb4-b3d4-746e062eb92a	0bc9c5f7-dc77-4f7d-bfbf-4b347a934b24	reverse	2.0600000000004	\N	failed	2026-03-02 17:00:21.894399	\N	\N
ef1cc435-0ca3-4c5f-9339-4bce197b0713	0bc9c5f7-dc77-4f7d-bfbf-4b347a934b24	reverse	2.269999999999527	\N	failed	2026-03-02 17:14:15.892156	\N	\N
4547050d-3ace-4b0d-a462-bb611e397625	0bc9c5f7-dc77-4f7d-bfbf-4b347a934b24	reverse	2.2100000000000364	\N	failed	2026-03-02 17:25:41.972499	\N	\N
2ecb8f88-2941-47e3-b568-7897557cd957	0bc9c5f7-dc77-4f7d-bfbf-4b347a934b24	reverse	2.300000000000182	\N	failed	2026-03-02 17:30:11.461837	\N	\N
\.


--
-- Data for Name: audio_files; Type: TABLE DATA; Schema: public; Owner: postgres
--

COPY public.audio_files (file_id, file_name, file_path, file_key, file_size, is_synced, created_at, updated_at, synced_at) FROM stdin;
5078f431-888e-455d-9700-8d7764870261	single_leg.mp3	/data/hustle2026/frontend/public/sounds/single_leg.mp3	file_v3_0010e_27d45a24-a56c-4c36-a38a-985f55e4372g	138765	t	2026-04-03 22:07:46.181514	2026-04-03 22:07:46.968269	2026-04-03 22:07:46.968259
563c400e-675c-4a37-b32b-df95860969b5	mt5.mp3	/data/hustle2026/frontend/public/sounds/mt5.mp3	file_v3_0010e_ea4cdacc-0087-48d7-acd5-d855216b274g	125805	t	2026-04-03 22:07:46.181537	2026-04-03 22:07:48.979566	2026-04-03 22:07:48.979558
7eedc221-e068-4665-b406-aae47ea2e6b7	net_asset.mp3	/data/hustle2026/frontend/public/sounds/net_asset.mp3	file_v3_0010e_eb64917c-7c4b-43e7-af81-cca96579233g	251085	t	2026-04-03 22:07:46.18153	2026-04-03 22:07:48.306465	2026-04-03 22:07:48.306456
9f721295-ed38-4333-bd99-61908145c7a8	MT5卡顿提示音.mp3	/data/hustle2026/frontend/public/sounds/MT5卡顿提示音.mp3	file_v3_0010e_c66decab-689b-498b-8c2f-cb4f275c84cg	125805	t	2026-04-03 22:07:46.181553	2026-04-03 22:07:50.893153	2026-04-03 22:07:50.893145
a25a4b7d-2036-486f-a244-0081bfc24164	外婆都在喊你快点去赚钱钱咯.mp3	/data/hustle2026/frontend/public/sounds/外婆都在喊你快点去赚钱钱咯.mp3	file_v3_0010e_72403f90-e512-45ef-81f0-a0ff4d5609ag	107520	t	2026-04-03 22:07:46.181542	2026-04-03 22:07:49.635734	2026-04-03 22:07:49.635726
c3e1d4a1-34d2-4e40-baa4-40c1f911a4aa	spread.mp3	/data/hustle2026/frontend/public/sounds/spread.mp3	file_v3_0010e_750f8f1f-8f62-4fa2-af09-4353a5de2f1g	107520	t	2026-04-03 22:07:46.181524	2026-04-03 22:07:47.614151	2026-04-03 22:07:47.614143
ef0ddf9a-d510-4605-a0cf-08507800c861	liquidation.mp3	/data/hustle2026/frontend/public/sounds/liquidation.mp3	file_v3_0010e_d64012af-6842-49b6-ba3c-3355c035585g	96960	t	2026-04-03 22:07:46.181547	2026-04-03 22:07:50.252041	2026-04-03 22:07:50.252034
68b63312-c82b-4097-a84c-d794a1a13ea0	爆仓提醒声.mp3	/data/hustle2026/frontend/public/sounds/爆仓提醒声.mp3	file_v3_0010e_a6e8eb17-1132-4a30-ad89-ab5beaf22d0g	96960	t	2026-04-03 22:07:46.181558	2026-04-03 22:23:47.173302	2026-04-03 22:07:51.54125
\.


--
-- Data for Name: market_data; Type: TABLE DATA; Schema: public; Owner: postgres
--

COPY public.market_data (id, symbol, platform, bid_price, ask_price, mid_price, "timestamp") FROM stdin;
\.


--
-- Data for Name: mt5_clients; Type: TABLE DATA; Schema: public; Owner: postgres
--

COPY public.mt5_clients (client_id, account_id, client_name, mt5_login, mt5_password, mt5_server, password_type, proxy_id, connection_status, is_active, priority, last_connected_at, last_disconnected_at, total_connections, failed_connections, avg_latency_ms, created_at, updated_at, created_by, bridge_url, is_system_service, agent_instance_name, bridge_service_name, bridge_service_port) FROM stdin;
7	6cb2345f-fcb6-404a-9349-94af86a57d61	MT5-02	5229471	Lk106504!	Bybit-Live-2	primary	\N	disconnected	t	1	\N	\N	0	0	\N	2026-04-03 04:19:49.089661	2026-04-03 16:04:31.133232	0bc9c5f7-dc77-4f7d-bfbf-4b347a934b24	\N	f	\N	\N	\N
1	6cb2345f-fcb6-404a-9349-94af86a57d61	MT5-01	2325036	800212xY!	Bybit-Live-2	primary	\N	connected	t	1	2026-04-03 22:43:37.921265	\N	0	1	\N	2026-03-22 21:48:59.190982	2026-04-03 22:43:37.985317	0bc9c5f7-dc77-4f7d-bfbf-4b347a934b24	\N	f	mt5-01	hustle-mt5-cq987	8002
3	6cb2345f-fcb6-404a-9349-94af86a57d61	MT5-Sys-Server	3971962	987987Cq!	Bybit-Live-2	readonly	\N	connected	t	1	2026-04-03 22:43:37.984372	\N	0	6	\N	2026-03-29 07:10:25.557519	2026-04-03 22:43:37.985328	0bc9c5f7-dc77-4f7d-bfbf-4b347a934b24	\N	t	bybit_system_service	hustle-mt5-system	8001
\.


--
-- Data for Name: mt5_instances; Type: TABLE DATA; Schema: public; Owner: postgres
--

COPY public.mt5_instances (instance_id, instance_name, server_ip, service_port, mt5_path, mt5_data_path, is_portable, deploy_path, auto_start, status, is_active, created_at, updated_at, created_by, instance_type, client_id) FROM stdin;
b5a31203-2752-444e-a0d4-71602e0c5115	MT5-01-实例	172.31.14.113	8002	D:\\MetaTrader 5-01\\terminal64.exe	D:\\MetaTrader 5-01	t	D:\\hustle-mt5-cq987	t	stopped	t	2026-03-30 17:33:40.164217	2026-03-31 18:00:23.598312	\N	primary	1
911903df-cd48-47b0-9793-0812ef523683	MT5-Sys-Server-实例	172.31.14.113	8001	C:\\Program Files\\MetaTrader 5\\terminal64.exe	C:\\Program Files\\MetaTrader 5	t	D:\\hustle-mt5-deploy	t	running	t	2026-03-29 16:26:36.93988	2026-04-01 15:14:19.441949	\N	primary	3
\.


--
-- Data for Name: notification_configs; Type: TABLE DATA; Schema: public; Owner: postgres
--

COPY public.notification_configs (config_id, service_type, is_enabled, config_data, created_at, updated_at) FROM stdin;
f101d225-7539-4f69-ae0f-d73a9d68da19	email	f	{"password": "", "username": "", "smtp_host": "smtp.gmail.com", "smtp_port": 587, "from_email": ""}	2026-03-05 21:06:18.182418	2026-03-05 21:06:18.182418
5c2fbeba-c801-46d9-badc-16625bb531b5	sms	f	{"provider": "aliyun", "sign_name": "", "access_key": "", "access_secret": ""}	2026-03-05 21:06:18.182418	2026-03-05 21:06:18.182418
3ba11638-7585-4fc8-ad3c-e12ed070501a	feishu	t	{"app_id": "test", "app_secret": "test"}	2026-03-05 21:06:18.182418	2026-04-03 22:07:46.130227
\.


--
-- Data for Name: notification_logs; Type: TABLE DATA; Schema: public; Owner: postgres
--

COPY public.notification_logs (log_id, user_id, template_key, service_type, recipient, title, content, status, error_message, sent_at, created_at) FROM stdin;
4bcf67c2-15b7-4bda-bc31-255133bba1cc	0bc9c5f7-dc77-4f7d-bfbf-4b347a934b24	single_leg_alert	feishu	ou_613cc2eabae277733bdee67edb3d8cc5	⚡ 单边配送预警	**配送不平衡提醒**\\nBinance仓库出现单边配送\\n\\n单边数量：{quantity}件\\n持续时间：5 min秒\\n配送方向：{direction}\\n\\n请尽快完成对冲配送，避免价格风险	sent	\N	2026-03-06 08:49:42.517286	2026-03-06 00:49:42.519292
27433405-5898-4035-bfbe-a8235b151b10	0bc9c5f7-dc77-4f7d-bfbf-4b347a934b24	single_leg_alert	feishu	ou_613cc2eabae277733bdee67edb3d8cc5	⚡ 单边配送预警	**配送不平衡提醒**\\nBinance仓库出现单边配送\\n\\n单边数量：{quantity}件\\n持续时间：5 min秒\\n配送方向：{direction}\\n\\n请尽快完成对冲配送，避免价格风险	sent	\N	2026-03-06 08:58:21.625022	2026-03-06 00:58:21.627044
5249bd6f-12c9-46b1-9c12-d5bc6208f2a5	0bc9c5f7-dc77-4f7d-bfbf-4b347a934b24	mt5_lag_alert	feishu	ou_613cc2eabae277733bdee67edb3d8cc5	⚠️ 配送系统延迟提醒	**系统响应异常**\\n配送系统出现延迟\\n\\n连接失败次数：{failure_count}次\\n最后响应时间：{last_response_time}\\n\\n请检查系统连接状态，必要时重启配送系统	sent	\N	2026-03-06 08:59:01.181674	2026-03-06 00:59:01.181674
4a6fafd9-b578-49ee-a315-58b46635ce63	0bc9c5f7-dc77-4f7d-bfbf-4b347a934b24	forward_open_spread_alert	feishu	ou_613cc2eabae277733bdee67edb3d8cc5	💰 优惠价格机会提醒	**价格优势通知**\\n当前价格差异：10.50元/件\\n优惠阈值：100.00元/件\\n\\n建议操作：接收优惠订单\\n预计收益：{estimated_profit}元\\n\\n这是一个不错的价格机会！	sent	\N	2026-03-06 08:59:12.225437	2026-03-06 00:59:12.225437
2b35af8d-5cef-4818-b8ca-29f1ab36becd	0bc9c5f7-dc77-4f7d-bfbf-4b347a934b24	account_verified	feishu	ou_613cc2eabae277733bdee67edb3d8cc5	✅ 账户认证成功	**认证通过**\\n恭喜您，账户认证已通过！\\n\\n账户名称：Test Account\\n认证时间：{verify_time}\\n\\n您现在可以开始使用配送服务	sent	\N	2026-03-06 08:59:19.853842	2026-03-06 00:59:19.853842
ee1dfb24-a2ea-406c-826b-e9273d4e5bf4	0bc9c5f7-dc77-4f7d-bfbf-4b347a934b24	binance_liquidation_alert	feishu	ou_613cc2eabae277733bdee67edb3d8cc5	🚨 A仓库安全线预警	**价格安全提醒**\\n当前价格：50500.00元\\n安全线价格：{liquidation_price}元\\n距离安全线：{distance}元\\n\\n正常\\n请密切关注价格变化，必要时调整仓位	sent	\N	2026-03-06 09:06:10.89652	2026-03-06 01:06:10.89652
6f5ac450-8f64-495d-919f-620273252351	0bc9c5f7-dc77-4f7d-bfbf-4b347a934b24	single_leg_alert	feishu	ou_613cc2eabae277733bdee67edb3d8cc5	⚡ 单边配送预警	**配送不平衡提醒**\\nBinance仓库出现单边配送\\n\\n单边数量：0.001件\\n持续时间：5分钟秒\\n配送方向：{direction}\\n\\n请尽快完成对冲配送，避免价格风险	sent	\N	2026-03-06 09:13:00.092271	2026-03-06 01:13:00.092271
cabbca65-23b6-41b6-a6ab-74465194fec7	0bc9c5f7-dc77-4f7d-bfbf-4b347a934b24	single_leg_alert	feishu	ou_613cc2eabae277733bdee67edb3d8cc5	⚡ 单边配送预警	**配送不平衡提醒**\\nBinance仓库出现单边配送\\n\\n单边数量：0.001件\\n持续时间：5分钟秒\\n配送方向：{direction}\\n\\n请尽快完成对冲配送，避免价格风险	sent	\N	2026-03-06 09:24:08.853838	2026-03-06 01:24:08.853838
cbba3932-5a55-4372-b9d1-5718e944a502	0bc9c5f7-dc77-4f7d-bfbf-4b347a934b24	single_leg_alert	feishu	ou_613cc2eabae277733bdee67edb3d8cc5	⚡ 单边配送预警	**配送不平衡提醒**\\nBinance仓库出现单边配送\\n\\n单边数量：0.001件\\n持续时间：5分钟秒\\n配送方向：{direction}\\n\\n请尽快完成对冲配送，避免价格风险	sent	\N	2026-03-06 09:25:56.428594	2026-03-06 01:25:56.429617
edba4cfc-ced4-43ad-81a7-1c4a1bd60111	0bc9c5f7-dc77-4f7d-bfbf-4b347a934b24	single_leg_alert	feishu	ou_613cc2eabae277733bdee67edb3d8cc5	⚡ 单边配送预警	**配送不平衡提醒**\\nBinance仓库出现单边配送\\n\\n单边数量：0.001件\\n持续时间：5分钟秒\\n配送方向：{direction}\\n\\n请尽快完成对冲配送，避免价格风险	sent	\N	2026-03-06 09:26:08.555116	2026-03-06 01:26:08.555116
996a34da-4a4f-4a0e-94c5-72947c3b799d	0bc9c5f7-dc77-4f7d-bfbf-4b347a934b24	single_leg_alert	feishu	ou_613cc2eabae277733bdee67edb3d8cc5	⚡ 单边配送预警	**配送不平衡提醒**\\nBinance仓库出现单边配送\\n\\n单边数量：0.001件\\n持续时间：5分钟秒\\n配送方向：{direction}\\n\\n请尽快完成对冲配送，避免价格风险	sent	\N	2026-03-06 09:35:10.766502	2026-03-06 01:35:10.766502
f429b83e-278d-44e5-b53b-8dcfee122523	0bc9c5f7-dc77-4f7d-bfbf-4b347a934b24	risk_warning	feishu	ou_613cc2eabae277733bdee67edb3d8cc5	⚠️ 库存预警通知	**库存状态**\\n商品名称：{product_name}\\n当前库存：{current_stock}件\\n预警阈值：100.00件\\n建议补货：{recommend_restock}件	sent	\N	2026-03-06 09:35:37.992434	2026-03-06 01:35:37.992434
5f738e42-260d-4a94-949a-5c63471b4aa4	0bc9c5f7-dc77-4f7d-bfbf-4b347a934b24	reverse_open_spread_alert	feishu	ou_613cc2eabae277733bdee67edb3d8cc5	💎 反向优惠机会	**反向价格优势**\\n当前价格差异：10.50元/件\\n优惠阈值：100.00元/件\\n\\n建议操作：接收反向订单\\n预计收益：{estimated_profit}元\\n\\n反向配送优惠机会出现！	sent	\N	2026-03-06 09:35:44.555091	2026-03-06 01:35:44.555091
a3d39730-a81f-47d4-b5bf-0d6c5a2ea925	0bc9c5f7-dc77-4f7d-bfbf-4b347a934b24	forward_open_spread_alert	feishu	ou_613cc2eabae277733bdee67edb3d8cc5	💰 优惠价格机会提醒	**价格优势通知**\\n当前价格差异：10.50元/件\\n优惠阈值：100.00元/件\\n\\n建议操作：接收优惠订单\\n预计收益：{estimated_profit}元\\n\\n这是一个不错的价格机会！	sent	\N	2026-03-06 09:35:49.867212	2026-03-06 01:35:49.867212
0bb547be-c893-498c-b70f-ee8e14f495ec	0bc9c5f7-dc77-4f7d-bfbf-4b347a934b24	system_maintenance	feishu	ou_613cc2eabae277733bdee67edb3d8cc5	🔧 系统维护通知	**维护公告**\\n维护时间：{maintenance_time}\\n维护内容：{maintenance_content}\\n预计恢复：{estimated_recovery}\\n\\n如有疑问请联系客服	sent	\N	2026-03-06 09:56:25.803561	2026-03-06 01:56:25.803561
3620e4fd-8e8d-4b0e-8b46-32640bc73a20	0bc9c5f7-dc77-4f7d-bfbf-4b347a934b24	single_leg_alert	feishu	ou_613cc2eabae277733bdee67edb3d8cc5	⚡ 单边配送预警	**配送不平衡提醒**\\nBinance仓库出现单边配送\\n\\n单边数量：0.001件\\n持续时间：5分钟秒\\n配送方向：{direction}\\n\\n请尽快完成对冲配送，避免价格风险	sent	\N	2026-03-06 15:41:24.72467	2026-03-06 07:41:24.72467
e817f9d9-b720-49ed-b894-ef04e12c8a82	66764cd6-d1c9-4468-a478-85b526a16927	single_leg_alert	feishu	ou_148845ec547cfffe26654bb11561ea3c	⚡ 单边配送预警	**配送不平衡提醒**\\nBinance仓库出现单边配送\\n\\n单边数量：0.001件\\n持续时间：5分钟秒\\n配送方向：{direction}\\n\\n请尽快完成对冲配送，避免价格风险	sent	\N	2026-03-06 16:03:55.598285	2026-03-06 08:03:55.598285
dd279a1b-df7e-4e0b-b874-1391594aec6a	66764cd6-d1c9-4468-a478-85b526a16927	mt5_lag_alert	feishu	ou_148845ec547cfffe26654bb11561ea3c	⚠️ 配送系统延迟提醒	**系统响应异常**\\n配送系统出现延迟\\n\\n连接失败次数：{failure_count}次\\n最后响应时间：{last_response_time}\\n\\n请检查系统连接状态，必要时重启配送系统	sent	\N	2026-03-06 16:04:07.254906	2026-03-06 08:04:07.254906
861bdad7-2c8b-4776-a042-2a3200fa6d75	66764cd6-d1c9-4468-a478-85b526a16927	binance_net_asset_alert	feishu	ou_148845ec547cfffe26654bb11561ea3c	💰 A仓库资产预警	**资产状况提醒**\\n当前A仓库净资产：{current_asset}元\\n预警阈值：100.00元\\n\\n资产已正常预警线\\n请及时关注资产变化	sent	\N	2026-03-06 16:04:21.892604	2026-03-06 08:04:21.892604
\.


--
-- Data for Name: notification_templates; Type: TABLE DATA; Schema: public; Owner: postgres
--

COPY public.notification_templates (template_id, template_key, template_name, category, title_template, content_template, enable_email, enable_sms, enable_feishu, priority, cooldown_seconds, is_active, created_at, updated_at, alert_sound, repeat_count, auto_check_enabled, popup_title_template, popup_content_template, alert_sound_file, alert_sound_repeat) FROM stdin;
8bb79d1d-3599-480d-8a2c-f1623420445b	trade_executed	订单配送完成	trading	🚚 您的订单已配送完成	**订单详情**\\n订单编号：{order_id}\\n商品名称：{product_name}\\n配送数量：{quantity}件\\n配送时间：{time}\\n配送状态：✅ 已签收	f	f	t	2	0	t	2026-03-05 21:06:18.182418	2026-03-05 21:06:18.182418	\N	3	t	\N	\N	\N	3
c7d3fc69-fd07-4785-8e53-829a9468e4ea	position_opened	新订单已接收	trading	📦 新订单已接收	**订单信息**\\n订单类型：{order_type}\\n商品规格：{specification}\\n订单数量：{quantity}件\\n预计配送时间：{estimated_time}	f	f	t	2	0	t	2026-03-05 21:06:18.182418	2026-03-05 21:06:18.182418	\N	3	t	\N	\N	\N	3
800f5ca1-0d4d-4210-ab75-ac7338aeace8	position_closed	订单已完成	trading	✅ 订单配送完成	**配送结果**\\n订单编号：{order_id}\\n配送结果：{result}\\n实际数量：{actual_quantity}件\\n客户评价：{feedback}	f	f	t	2	0	t	2026-03-05 21:06:18.182418	2026-03-05 21:06:18.182418	\N	3	t	\N	\N	\N	3
10fdea50-3dd0-49d7-a09c-cd0b1e5da5fa	balance_alert	账户余额提醒	risk	⚠️ 账户余额不足提醒	**余额预警**\\n尊敬的客户，您的账户余额已低于安全线\\n\\n当前余额：{balance}元\\n建议充值：{recommend_amount}元\\n\\n请及时处理，避免影响配送服务	f	f	t	3	0	t	2026-03-05 21:06:18.182418	2026-03-05 21:06:18.182418	\N	3	t	\N	\N	\N	3
b71d2857-25a5-487d-864a-c31412beff53	risk_warning	库存预警	risk	⚠️ 库存预警通知	**库存状态**\\n商品名称：{product_name}\\n当前库存：{current_stock}件\\n预警阈值：{threshold}件\\n建议补货：{recommend_restock}件	f	f	t	4	0	t	2026-03-05 21:06:18.182418	2026-03-05 21:06:18.182418	\N	3	t	\N	\N	\N	3
46d51045-7ddd-4539-92e1-cc165cc970f4	margin_call	预付款不足	risk	🔴 预付款不足警告	**紧急通知**\\n您的预付款余额不足\\n\\n当前预付款：{margin}元\\n所需预付款：{required_margin}元\\n缺口金额：{shortage}元\\n\\n请立即充值，避免订单被取消	f	f	t	4	0	t	2026-03-05 21:06:18.182418	2026-03-05 21:06:18.182418	\N	3	t	\N	\N	\N	3
ef819efc-43d2-4cfe-b68b-8321d341a96d	forward_open_spread_alert	优惠价格提醒	risk	💰 优惠价格机会提醒	**价格优势通知**\\n当前价格差异：{spread}元/件\\n优惠阈值：{threshold}元/件\\n\\n建议操作：接收优惠订单\\n预计收益：{estimated_profit}元\\n\\n这是一个不错的价格机会！	f	f	t	3	0	t	2026-03-05 21:06:18.182418	2026-03-05 21:06:18.182418	\N	3	t	\N	\N	\N	3
17708f96-971a-48dc-a714-cb5e3c52e33f	forward_close_spread_alert	价格回归提醒	risk	📊 价格回归通知	**价格变化提醒**\\n当前价格差异：{spread}元/件\\n回归阈值：{threshold}元/件\\n\\n建议操作：完成订单配送\\n当前收益：{current_profit}元\\n\\n价格已回归正常区间	f	f	t	3	0	t	2026-03-05 21:06:18.182418	2026-03-05 21:06:18.182418	\N	3	t	\N	\N	\N	3
98572144-b63b-4b25-82cd-1d2edecf5b09	reverse_open_spread_alert	反向优惠提醒	risk	💎 反向优惠机会	**反向价格优势**\\n当前价格差异：{spread}元/件\\n优惠阈值：{threshold}元/件\\n\\n建议操作：接收反向订单\\n预计收益：{estimated_profit}元\\n\\n反向配送优惠机会出现！	f	f	t	3	0	t	2026-03-05 21:06:18.182418	2026-03-05 21:06:18.182418	\N	3	t	\N	\N	\N	3
a809f0c4-abb8-40fc-bf88-39d2d02faaec	reverse_close_spread_alert	反向价格回归	risk	📈 反向价格回归	**反向价格变化**\\n当前价格差异：{spread}元/件\\n回归阈值：{threshold}元/件\\n\\n建议操作：完成反向配送\\n当前收益：{current_profit}元\\n\\n反向价格已回归正常	f	f	t	3	0	t	2026-03-05 21:06:18.182418	2026-03-05 21:06:18.182418	\N	3	t	\N	\N	\N	3
ee845657-16da-4345-986b-e7911877af41	mt5_lag_alert	配送系统延迟	risk	⚠️ 配送系统延迟提醒	**系统响应异常**\\n配送系统出现延迟\\n\\n连接失败次数：{failure_count}次\\n最后响应时间：{last_response_time}\\n\\n请检查系统连接状态，必要时重启配送系统	f	f	t	4	0	t	2026-03-05 21:06:18.182418	2026-03-05 21:06:18.182418	\N	3	t	\N	\N	\N	3
de34a278-49ad-4f24-a15c-61ea160c01b7	binance_net_asset_alert	A仓库资产提醒	risk	💰 A仓库资产预警	**资产状况提醒**\\n当前A仓库净资产：{current_asset}元\\n预警阈值：{threshold}元\\n\\n资产已{status}预警线\\n请及时关注资产变化	f	f	t	3	0	t	2026-03-05 21:06:18.182418	2026-03-05 21:06:18.182418	\N	3	t	\N	\N	\N	3
1244e3ad-289d-4d03-9f3d-556b0c05e2bf	bybit_net_asset_alert	B仓库资产提醒	risk	💰 B仓库资产预警	**资产状况提醒**\\n当前B仓库净资产：{current_asset}元\\n预警阈值：{threshold}元\\n\\n资产已{status}预警线\\n请及时关注资产变化	f	f	t	3	0	t	2026-03-05 21:06:18.182418	2026-03-05 21:06:18.182418	\N	3	t	\N	\N	\N	3
730fa329-9f34-4663-9de9-8c3fff213e27	binance_liquidation_alert	A仓库安全线提醒	risk	🚨 A仓库安全线预警	**价格安全提醒**\\n当前价格：{current_price}元\\n安全线价格：{liquidation_price}元\\n距离安全线：{distance}元\\n\\n{status}\\n请密切关注价格变化，必要时调整仓位	f	f	t	4	0	t	2026-03-05 21:06:18.182418	2026-03-05 21:06:18.182418	\N	3	t	\N	\N	\N	3
5fc8c8c8-ccd1-43f2-837e-7cc7704aa41d	bybit_liquidation_alert	B仓库安全线提醒	risk	🚨 B仓库安全线预警	**价格安全提醒**\\n当前价格：{current_price}元\\n安全线价格：{liquidation_price}元\\n距离安全线：{distance}元\\n\\n{status}\\n请密切关注价格变化，必要时调整仓位	f	f	t	4	0	t	2026-03-05 21:06:18.182418	2026-03-05 21:06:18.182418	\N	3	t	\N	\N	\N	3
91f2f68b-95bb-49e5-9c7e-2ff347162bbc	single_leg_alert	单边配送提醒	risk	⚡ 单边配送预警	**配送不平衡提醒**\\n{exchange}仓库出现单边配送\\n\\n单边数量：{quantity}件\\n持续时间：{duration}秒\\n配送方向：{direction}\\n\\n请尽快完成对冲配送，避免价格风险	f	f	t	4	0	t	2026-03-05 21:06:18.182418	2026-03-05 21:06:18.182418	\N	3	t	\N	\N	\N	3
caec7688-207c-4fc5-80c4-c89c7bcc0518	system_maintenance	系统维护通知	system	🔧 系统维护通知	**维护公告**\\n维护时间：{maintenance_time}\\n维护内容：{maintenance_content}\\n预计恢复：{estimated_recovery}\\n\\n如有疑问请联系客服	f	f	t	3	0	t	2026-03-05 21:06:18.182418	2026-03-05 21:06:18.182418	\N	3	t	\N	\N	\N	3
8a394eba-931d-4d84-8ffd-1473a74f664d	account_verified	账户认证成功	system	✅ 账户认证成功	**认证通过**\\n恭喜您，账户认证已通过！\\n\\n账户名称：{account_name}\\n认证时间：{verify_time}\\n\\n您现在可以开始使用配送服务	f	f	t	2	0	t	2026-03-05 21:06:18.182418	2026-03-05 21:06:18.182418	\N	3	t	\N	\N	\N	3
d38af4b9-0700-48ad-9630-81e057750c2f	order_cancelled	订单已取消	trading	❌ 订单已取消	**取消通知**\\n订单编号：{order_id}\\n取消原因：{reason}\\n取消时间：{cancel_time}\\n\\n如有疑问请联系客服	f	f	t	2	0	t	2026-03-05 21:06:18.182418	2026-03-05 21:06:18.182418	\N	3	t	\N	\N	\N	3
301ea8a0-6046-4adb-b8a8-fe1bb5e4ab9d	total_net_asset_alert	总资产提醒	risk	💰 总资产预警	**总资产状况提醒**\n当前总资产：{current_asset}元\n预警阈值：{threshold}元\n\n资产已{status}预警线\n请及时关注资产变化	f	f	t	3	300	t	2026-03-06 13:29:36.785706	2026-03-06 13:29:36.785706	\N	3	t	\N	\N	\N	3
17e32453-d64b-4892-bf28-b2ee8d1ad838	mt5_client_error	MT5 客户端错误	system	🚨 {title}	{content}	f	f	t	4	300	t	2026-03-31 16:25:15.794566	2026-03-31 16:25:15.794566	\N	3	t	\N	\N	\N	3
b90ce92e-b410-44dd-8a8a-c913df311510	mt5_client_warning	MT5 客户端警告	system	⚠️ {title}	{content}	f	f	t	3	600	t	2026-03-31 16:25:15.794566	2026-03-31 16:25:15.794566	\N	3	t	\N	\N	\N	3
4b04fd44-2d2e-42df-ba9b-392051ce9cbd	mt5_client_info	MT5 客户端信息	system	ℹ️ {title}	{content}	f	f	t	2	1800	t	2026-03-31 16:25:15.794566	2026-03-31 16:25:15.794566	\N	3	t	\N	\N	\N	3
\.


--
-- Data for Name: notifications; Type: TABLE DATA; Schema: public; Owner: postgres
--

COPY public.notifications (notification_id, user_id, type, title, message, is_read, created_at) FROM stdin;
\.


--
-- Data for Name: order_records; Type: TABLE DATA; Schema: public; Owner: postgres
--

COPY public.order_records (order_id, account_id, symbol, order_side, order_type, price, qty, filled_qty, status, platform_order_id, create_time, update_time, fee, source) FROM stdin;
\.


--
-- Data for Name: permissions; Type: TABLE DATA; Schema: public; Owner: postgres
--

COPY public.permissions (permission_id, permission_name, permission_code, resource_type, resource_path, http_method, description, parent_id, sort_order, is_active, created_at, updated_at) FROM stdin;
c060adfa-d126-4366-8b59-f557cdb6f908	用户列表	user:list	api	/api/v1/users	GET	查看用户列表	\N	0	t	2026-02-25 08:26:52.243327	2026-02-25 08:26:52.243327
bdf67ee9-71ba-4892-b499-4cf048c3f0fc	用户详情	user:detail	api	/api/v1/users/{id}	GET	查看用户详情	\N	0	t	2026-02-25 08:26:52.243327	2026-02-25 08:26:52.243327
ae04fb5d-e4ef-4173-91ec-168aa812c17f	创建用户	user:create	api	/api/v1/users	POST	创建新用户	\N	0	t	2026-02-25 08:26:52.243327	2026-02-25 08:26:52.243327
6d83db88-d70b-49c9-8b98-ad617f49a24f	编辑用户	user:update	api	/api/v1/users/{id}	PUT	编辑用户信息	\N	0	t	2026-02-25 08:26:52.243327	2026-02-25 08:26:52.243327
f05b272c-dfee-4354-a289-4762787789da	删除用户	user:delete	api	/api/v1/users/{id}	DELETE	删除用户	\N	0	t	2026-02-25 08:26:52.243327	2026-02-25 08:26:52.243327
aa5381b9-60f0-4cea-8c5f-2274e56a654b	角色列表	role:list	api	/api/v1/roles	GET	查看角色列表	\N	0	t	2026-02-25 08:26:52.243327	2026-02-25 08:26:52.243327
e3a66a83-0fc3-4973-848d-e0a23de86a52	创建角色	role:create	api	/api/v1/roles	POST	创建新角色	\N	0	t	2026-02-25 08:26:52.243327	2026-02-25 08:26:52.243327
82ad46cb-092f-4487-b272-2daf5541c897	编辑角色	role:update	api	/api/v1/roles/{id}	PUT	编辑角色信息	\N	0	t	2026-02-25 08:26:52.243327	2026-02-25 08:26:52.243327
7bd2845d-95e6-4d84-8c40-404910e7a352	删除角色	role:delete	api	/api/v1/roles/{id}	DELETE	删除角色	\N	0	t	2026-02-25 08:26:52.243327	2026-02-25 08:26:52.243327
4c4efc0f-d514-47c6-b4fe-708c6b8e9f9c	分配权限	role:assign_permission	api	/api/v1/roles/{id}/permissions	POST	为角色分配权限	\N	0	t	2026-02-25 08:26:52.243327	2026-02-25 08:26:52.243327
a10cceed-9994-40f9-97f8-b85da58309c9	安全组件列表	security:list	api	/api/v1/security/components	GET	查看安全组件列表	\N	0	t	2026-02-25 08:26:52.243327	2026-02-25 08:26:52.243327
c1f876b7-82be-4652-b49e-e29f93418adf	启用组件	security:enable	api	/api/v1/security/components/{id}/enable	POST	启用安全组件	\N	0	t	2026-02-25 08:26:52.243327	2026-02-25 08:26:52.243327
5feb4705-3e15-41f0-abe9-54a687cb8378	禁用组件	security:disable	api	/api/v1/security/components/{id}/disable	POST	禁用安全组件	\N	0	t	2026-02-25 08:26:52.243327	2026-02-25 08:26:52.243327
a429e651-676d-470a-b78e-72387bd23921	配置组件	security:config	api	/api/v1/security/components/{id}/config	PUT	配置安全组件	\N	0	t	2026-02-25 08:26:52.243327	2026-02-25 08:26:52.243327
97ba4968-c723-4599-9615-849f6da31eae	证书列表	ssl:list	api	/api/v1/ssl/certificates	GET	查看SSL证书列表	\N	0	t	2026-02-25 08:26:52.243327	2026-02-25 08:26:52.243327
619b5ea4-4839-40ff-88c2-05c940ff3b15	上传证书	ssl:upload	api	/api/v1/ssl/certificates	POST	上传SSL证书	\N	0	t	2026-02-25 08:26:52.243327	2026-02-25 08:26:52.243327
fc27a1d1-6ef5-484e-b32b-47f5f3d7e81c	部署证书	ssl:deploy	api	/api/v1/ssl/certificates/{id}/deploy	POST	部署SSL证书	\N	0	t	2026-02-25 08:26:52.243327	2026-02-25 08:26:52.243327
0ec6ee5f-2ffa-4dda-9fc4-3162eb855547	删除证书	ssl:delete	api	/api/v1/ssl/certificates/{id}	DELETE	删除SSL证书	\N	0	t	2026-02-25 08:26:52.243327	2026-02-25 08:26:52.243327
5805e19e-c3e7-4086-bd7a-6a963539ef5e	交易列表	trading:list	api	/api/v1/trading	GET	查看交易列表	\N	0	t	2026-02-25 08:26:52.243327	2026-02-25 08:26:52.243327
50303ba1-ca2c-491d-81b8-8b95e436c9da	执行交易	trading:execute	api	/api/v1/trading/execute	POST	执行交易操作	\N	0	t	2026-02-25 08:26:52.243327	2026-02-25 08:26:52.243327
09070d89-9465-4210-80ab-631cb7589e80	查看角色详情	role:detail	api	/api/v1/rbac/roles/{id}	\N	\N	\N	0	t	2026-02-25 17:47:03.998591	2026-02-25 17:47:03.998591
bb580d29-f140-4664-9f9d-61459971cd91	查看权限列表	permission:list	api	/api/v1/rbac/permissions	\N	\N	\N	0	t	2026-02-25 17:47:04.008244	2026-02-25 17:47:04.008244
e63b6f2e-78dc-479c-904e-9f22f9b7b21a	创建权限	permission:create	api	/api/v1/rbac/permissions	\N	\N	\N	0	t	2026-02-25 17:47:04.009258	2026-02-25 17:47:04.009258
3374bf53-16bd-47f2-91b5-f8190f38554b	更新权限	permission:update	api	/api/v1/rbac/permissions/{id}	\N	\N	\N	0	t	2026-02-25 17:47:04.011259	2026-02-25 17:47:04.011259
9933b355-d93d-4bed-87d8-3595fc72ee00	删除权限	permission:delete	api	/api/v1/rbac/permissions/{id}	\N	\N	\N	0	t	2026-02-25 17:47:04.012247	2026-02-25 17:47:04.012247
8662b74a-6abe-45a5-b2c7-98f621d8320a	查看策略列表	strategy:list	api	/api/v1/strategies	\N	\N	\N	0	t	2026-02-25 17:47:04.015258	2026-02-25 17:47:04.015258
5908338f-ddd4-4683-ac52-f8d7ceb897a1	创建策略	strategy:create	api	/api/v1/strategies	\N	\N	\N	0	t	2026-02-25 17:47:04.016243	2026-02-25 17:47:04.016243
2511d363-1467-4683-9fb7-aec385271e03	更新策略	strategy:update	api	/api/v1/strategies/{id}	\N	\N	\N	0	t	2026-02-25 17:47:04.017245	2026-02-25 17:47:04.017245
898e3a3b-54e7-49a4-adff-a02e09a04800	删除策略	strategy:delete	api	/api/v1/strategies/{id}	\N	\N	\N	0	t	2026-02-25 17:47:04.019243	2026-02-25 17:47:04.019243
84f95820-f480-4b44-af1b-cbffc5175f0c	总控面板	menu:admin:dashboard	menu	/admin/	\N	admin站 - 总控面板：服务器状态、MT5客户端、用户资金汇总	\N	100	t	2026-04-03 21:46:26.931476	2026-04-03 21:46:26.931476
23347b45-c1a6-4a70-babe-4961753f2b94	WebSocket监控	menu:admin:ws_monitor	menu	/admin/ws-monitor	\N	admin站 - WebSocket连接监控、推流服务管理	\N	110	t	2026-04-03 21:46:26.931476	2026-04-03 21:46:26.931476
c0ec87ac-7c49-4782-866c-3905ed2fc201	点差记录分析	menu:admin:spread	menu	/admin/spread	\N	admin站 - 历史点差数据查询与图表分析	\N	120	t	2026-04-03 21:46:26.931476	2026-04-03 21:46:26.931476
2eaa594f-97e8-4074-a017-19cf390ea9f5	策略配置	menu:admin:strategies	menu	/admin/strategies	\N	admin站 - 策略执行流程配置（时序参数）	\N	130	t	2026-04-03 21:46:26.931476	2026-04-03 21:46:26.931476
d281c5cd-c555-4caa-89fd-cad172a26f05	用户管理	menu:admin:users	menu	/admin/users	\N	admin站 - 用户CRUD、MT5客户端管理、Bridge部署	\N	140	t	2026-04-03 21:46:26.931476	2026-04-03 21:46:26.931476
9e4afcc1-f089-4a6d-8d84-2973c83ab579	系统管理	menu:admin:system	menu	/admin/system	\N	admin站 - 角色权限、通知、安全组件、SSL、版本控制	\N	150	t	2026-04-03 21:46:26.931476	2026-04-03 21:46:26.931476
461a45c2-68f6-4a59-8259-8e91e0533195	控制面板	menu:go:dashboard	menu	/go/	\N	go站 - 套利交易控制面板、实时行情	\N	200	t	2026-04-03 21:46:26.931476	2026-04-03 21:46:26.931476
e47a4689-2037-4f69-b9e0-ff0b0703969f	交易历史数据	menu:go:trading	menu	/go/trading	\N	go站 - 历史交易记录查询	\N	210	t	2026-04-03 21:46:26.931476	2026-04-03 21:46:26.931476
3197647a-a499-4817-8c47-1ef19da51ff2	挂单查询	menu:go:pending_orders	menu	/go/pending-orders	\N	go站 - 当前挂单状态查询	\N	220	t	2026-04-03 21:46:26.931476	2026-04-03 21:46:26.931476
02ee7a8c-8dc5-4462-9b41-470c79fcc671	收益总览	menu:www:overview	menu	/www/	\N	www站 - 观察员/交易员实时收益查看	\N	300	t	2026-04-03 21:46:26.931476	2026-04-03 21:46:26.931476
4199df10-1c1d-422b-9719-daff98fa21b6	历史记录	menu:www:history	menu	/www/history	\N	www站 - 历史收益记录	\N	310	t	2026-04-03 21:46:26.931476	2026-04-03 21:46:26.931476
\.


--
-- Data for Name: platforms; Type: TABLE DATA; Schema: public; Owner: postgres
--

COPY public.platforms (platform_id, platform_name, api_base_url, ws_base_url, account_api_type, market_api_type) FROM stdin;
1	binance	https://fapi.binance.com	wss://fstream.binance.com	binance_futures	binance_futures
2	bybit	https://api.bybit.com	wss://stream.bybit.com	bybit_v5	bybit_mt5
\.


--
-- Data for Name: positions; Type: TABLE DATA; Schema: public; Owner: postgres
--

COPY public.positions (position_id, user_id, account_id, symbol, platform, side, entry_price, current_price, quantity, leverage, unrealized_pnl, realized_pnl, margin_used, is_open, open_time, close_time, update_time) FROM stdin;
\.


--
-- Data for Name: proxy_pool; Type: TABLE DATA; Schema: public; Owner: postgres
--

COPY public.proxy_pool (id, proxy_type, host, port, username, password, provider, region, ip_address, expire_time, status, health_score, last_check_time, total_requests, failed_requests, avg_latency_ms, extra_metadata, created_at, updated_at, created_by) FROM stdin;
\.


--
-- Data for Name: risk_alerts; Type: TABLE DATA; Schema: public; Owner: postgres
--

COPY public.risk_alerts (alert_id, user_id, alert_level, alert_message, create_time, expire_time) FROM stdin;
\.


--
-- Data for Name: risk_settings; Type: TABLE DATA; Schema: public; Owner: postgres
--

COPY public.risk_settings (settings_id, user_id, binance_net_asset, bybit_mt5_net_asset, total_net_asset, binance_liquidation_price, bybit_mt5_liquidation_price, mt5_lag_count, reverse_open_price, reverse_open_sync_count, reverse_close_price, reverse_close_sync_count, forward_open_price, forward_open_sync_count, forward_close_price, forward_close_sync_count, create_time, update_time, spread_alert_sound, net_asset_alert_sound, mt5_alert_sound, liquidation_alert_sound, spread_alert_repeat_count, net_asset_alert_repeat_count, mt5_alert_repeat_count, liquidation_alert_repeat_count, single_leg_alert_sound, single_leg_alert_repeat_count) FROM stdin;
4561c5cf-8203-4ed8-8e85-62d6b6576fec	0bc9c5f7-dc77-4f7d-bfbf-4b347a934b24	50	50	600	2000	2000	20	3	3	1.5	3	3	3	1.5	3	2026-02-20 17:51:35.678918	2026-03-21 23:29:35.857863	/uploads/alert_sounds/0bc9c5f7-dc77-4f7d-bfbf-4b347a934b24_spread.mp3	/uploads/alert_sounds/0bc9c5f7-dc77-4f7d-bfbf-4b347a934b24_net_asset.mp3	/uploads/alert_sounds/0bc9c5f7-dc77-4f7d-bfbf-4b347a934b24_mt5.mp3	/uploads/alert_sounds/0bc9c5f7-dc77-4f7d-bfbf-4b347a934b24_liquidation.mp3	3	3	3	3	/uploads/alert_sounds/0bc9c5f7-dc77-4f7d-bfbf-4b347a934b24_single_leg.mp3	3
f238538b-0d23-49cb-8103-2ca42d851c16	66764cd6-d1c9-4468-a478-85b526a16927	99999	99999	0	10	10	5	9.99	9	1.23	9	9.99	9	1.23	9	2026-03-22 22:23:16.626263	2026-03-22 23:12:31.391441	\N	\N	\N	\N	3	3	3	3	\N	3
\.


--
-- Data for Name: role_permissions; Type: TABLE DATA; Schema: public; Owner: postgres
--

COPY public.role_permissions (id, role_id, permission_id, granted_at, granted_by) FROM stdin;
c42952fc-6a16-47e1-9c88-ad03b01d8440	8e25c438-70a5-4d9b-8634-9f16ab2cb1f3	c060adfa-d126-4366-8b59-f557cdb6f908	2026-03-01 15:44:07.421523	\N
27533694-ca84-4189-94e5-e32f3b75065a	8e25c438-70a5-4d9b-8634-9f16ab2cb1f3	bdf67ee9-71ba-4892-b499-4cf048c3f0fc	2026-03-01 15:44:07.441374	\N
33bae0ea-1349-4319-9c7b-e7a7cb48bf8b	8e25c438-70a5-4d9b-8634-9f16ab2cb1f3	ae04fb5d-e4ef-4173-91ec-168aa812c17f	2026-03-01 15:44:07.441374	\N
90804b85-6de3-4887-8767-d37e2d1d8936	8e25c438-70a5-4d9b-8634-9f16ab2cb1f3	6d83db88-d70b-49c9-8b98-ad617f49a24f	2026-03-01 15:44:07.441374	\N
97434e46-d8f2-476a-9010-2d1235b87757	8e25c438-70a5-4d9b-8634-9f16ab2cb1f3	f05b272c-dfee-4354-a289-4762787789da	2026-03-01 15:44:07.441374	\N
96486687-ed64-4e25-be5e-49b7150d0185	8e25c438-70a5-4d9b-8634-9f16ab2cb1f3	aa5381b9-60f0-4cea-8c5f-2274e56a654b	2026-03-01 15:44:07.441374	\N
c9ecc604-96a7-4344-bc1b-a2337911f8d8	8e25c438-70a5-4d9b-8634-9f16ab2cb1f3	09070d89-9465-4210-80ab-631cb7589e80	2026-03-01 15:44:07.441374	\N
0d746e5a-28b5-4e7c-baa2-216a43e7ee74	8e25c438-70a5-4d9b-8634-9f16ab2cb1f3	e3a66a83-0fc3-4973-848d-e0a23de86a52	2026-03-01 15:44:07.450979	\N
467ee073-6752-42b7-8772-baa0a690f221	8e25c438-70a5-4d9b-8634-9f16ab2cb1f3	82ad46cb-092f-4487-b272-2daf5541c897	2026-03-01 15:44:07.452514	\N
7d7890e9-e587-4ce4-8472-e23039306e39	8e25c438-70a5-4d9b-8634-9f16ab2cb1f3	7bd2845d-95e6-4d84-8c40-404910e7a352	2026-03-01 15:44:07.452514	\N
1566c42c-63ec-4f1f-989e-0845b68f3ef4	8e25c438-70a5-4d9b-8634-9f16ab2cb1f3	4c4efc0f-d514-47c6-b4fe-708c6b8e9f9c	2026-03-01 15:44:07.455548	\N
852fa424-fd13-415f-9db0-9d53a5d7559d	8e25c438-70a5-4d9b-8634-9f16ab2cb1f3	bb580d29-f140-4664-9f9d-61459971cd91	2026-03-01 15:44:07.456577	\N
bf96f758-b0c0-4698-a9c1-1db221e3630f	8e25c438-70a5-4d9b-8634-9f16ab2cb1f3	e63b6f2e-78dc-479c-904e-9f22f9b7b21a	2026-03-01 15:44:07.457589	\N
5ac5a95d-1110-4263-b9db-6d1637caa970	8e25c438-70a5-4d9b-8634-9f16ab2cb1f3	3374bf53-16bd-47f2-91b5-f8190f38554b	2026-03-01 15:44:07.458582	\N
12ac1e0f-a4ba-4278-a15d-b313a9942969	8e25c438-70a5-4d9b-8634-9f16ab2cb1f3	9933b355-d93d-4bed-87d8-3595fc72ee00	2026-03-01 15:44:07.460582	\N
89cda226-e2a3-48df-b8c7-8c8dfaaafc48	8e25c438-70a5-4d9b-8634-9f16ab2cb1f3	a10cceed-9994-40f9-97f8-b85da58309c9	2026-03-01 15:44:07.461588	\N
116332cc-7857-4117-8a73-58df580fe8f8	8e25c438-70a5-4d9b-8634-9f16ab2cb1f3	c1f876b7-82be-4652-b49e-e29f93418adf	2026-03-01 15:44:07.462571	\N
66c33f83-fa36-485d-b48b-8a829af493de	8e25c438-70a5-4d9b-8634-9f16ab2cb1f3	5feb4705-3e15-41f0-abe9-54a687cb8378	2026-03-01 15:44:07.463573	\N
fc72e3fb-6c8e-4818-b1f2-247a218eb052	8e25c438-70a5-4d9b-8634-9f16ab2cb1f3	a429e651-676d-470a-b78e-72387bd23921	2026-03-01 15:44:07.465566	\N
8db828c4-845a-47ef-aa26-45d98ea33cb8	8e25c438-70a5-4d9b-8634-9f16ab2cb1f3	97ba4968-c723-4599-9615-849f6da31eae	2026-03-01 15:44:07.466597	\N
b7d2ef77-2cb6-430d-bcfa-66826948b9ff	8e25c438-70a5-4d9b-8634-9f16ab2cb1f3	619b5ea4-4839-40ff-88c2-05c940ff3b15	2026-03-01 15:44:07.467577	\N
25077506-2ec2-4fd0-b00a-0c743d49eb2d	8e25c438-70a5-4d9b-8634-9f16ab2cb1f3	fc27a1d1-6ef5-484e-b32b-47f5f3d7e81c	2026-03-01 15:44:07.468594	\N
ea3826ed-5efd-4b1f-aba2-ba87016abbb6	8e25c438-70a5-4d9b-8634-9f16ab2cb1f3	0ec6ee5f-2ffa-4dda-9fc4-3162eb855547	2026-03-01 15:44:07.470588	\N
da3e13c4-da8c-488c-96e0-fd027087bcfa	8e25c438-70a5-4d9b-8634-9f16ab2cb1f3	50303ba1-ca2c-491d-81b8-8b95e436c9da	2026-03-01 15:44:07.471578	\N
10628f09-4155-4e9c-a537-155ac2968f15	8e25c438-70a5-4d9b-8634-9f16ab2cb1f3	5805e19e-c3e7-4086-bd7a-6a963539ef5e	2026-03-01 15:44:07.472568	\N
d85a28f1-0e25-4a46-b675-235818fd5efb	8e25c438-70a5-4d9b-8634-9f16ab2cb1f3	8662b74a-6abe-45a5-b2c7-98f621d8320a	2026-03-01 15:44:07.473594	\N
9994a4a2-6448-46ab-8d4b-906f1caf3401	8e25c438-70a5-4d9b-8634-9f16ab2cb1f3	5908338f-ddd4-4683-ac52-f8d7ceb897a1	2026-03-01 15:44:07.475571	\N
97cb6454-cebc-4145-b58c-ce669111f8fd	8e25c438-70a5-4d9b-8634-9f16ab2cb1f3	2511d363-1467-4683-9fb7-aec385271e03	2026-03-01 15:44:07.476568	\N
bf4d0df5-c961-4b28-a4d4-af5e5ff545e5	8e25c438-70a5-4d9b-8634-9f16ab2cb1f3	898e3a3b-54e7-49a4-adff-a02e09a04800	2026-03-01 15:44:07.477586	\N
e7f82c2b-db6a-4628-8af3-6ef877b8542c	63ad1a14-2623-4287-9dbf-dae8429c667f	c060adfa-d126-4366-8b59-f557cdb6f908	2026-03-01 15:44:07.49397	\N
3446acc7-1262-4b55-b7cb-76ce9c1fe880	63ad1a14-2623-4287-9dbf-dae8429c667f	bdf67ee9-71ba-4892-b499-4cf048c3f0fc	2026-03-01 15:44:07.494967	\N
37823c22-1a15-471a-9498-333a770c1975	63ad1a14-2623-4287-9dbf-dae8429c667f	ae04fb5d-e4ef-4173-91ec-168aa812c17f	2026-03-01 15:44:07.495965	\N
87865a3c-567d-42a3-a347-c2a7b44c4e3a	63ad1a14-2623-4287-9dbf-dae8429c667f	6d83db88-d70b-49c9-8b98-ad617f49a24f	2026-03-01 15:44:07.497963	\N
a9b4058d-397c-482c-8a45-e71e8ef9c6be	63ad1a14-2623-4287-9dbf-dae8429c667f	f05b272c-dfee-4354-a289-4762787789da	2026-03-01 15:44:07.498948	\N
799bab44-0c70-4d2a-a4cb-c36a69ceb8cf	63ad1a14-2623-4287-9dbf-dae8429c667f	aa5381b9-60f0-4cea-8c5f-2274e56a654b	2026-03-01 15:44:07.500947	\N
41244c29-7530-449b-b71c-3b7fb3df8c72	63ad1a14-2623-4287-9dbf-dae8429c667f	09070d89-9465-4210-80ab-631cb7589e80	2026-03-01 15:44:07.501963	\N
8f59e813-9e28-47de-a3a9-401a51e8bea8	63ad1a14-2623-4287-9dbf-dae8429c667f	e3a66a83-0fc3-4973-848d-e0a23de86a52	2026-03-01 15:44:07.503959	\N
b85957a7-de6b-4af3-81e7-cbd3d9d4c7d8	63ad1a14-2623-4287-9dbf-dae8429c667f	82ad46cb-092f-4487-b272-2daf5541c897	2026-03-01 15:44:07.504945	\N
847d76e4-e441-4112-90f0-8e8113f98974	63ad1a14-2623-4287-9dbf-dae8429c667f	7bd2845d-95e6-4d84-8c40-404910e7a352	2026-03-01 15:44:07.505946	\N
8f85a8a5-3401-46e2-8887-ee428a07fda4	63ad1a14-2623-4287-9dbf-dae8429c667f	4c4efc0f-d514-47c6-b4fe-708c6b8e9f9c	2026-03-01 15:44:07.506957	\N
0b806cac-edb4-41ba-868c-41b4da1501c1	63ad1a14-2623-4287-9dbf-dae8429c667f	bb580d29-f140-4664-9f9d-61459971cd91	2026-03-01 15:44:07.508953	\N
ae9dbd65-1ebc-4192-9136-5398e690db47	63ad1a14-2623-4287-9dbf-dae8429c667f	e63b6f2e-78dc-479c-904e-9f22f9b7b21a	2026-03-01 15:44:07.509965	\N
d9a96fb4-c1fb-4eb8-bc34-cbe2a077c26c	63ad1a14-2623-4287-9dbf-dae8429c667f	3374bf53-16bd-47f2-91b5-f8190f38554b	2026-03-01 15:44:07.510959	\N
b362ad53-b068-481f-a793-36b9c6fe8feb	63ad1a14-2623-4287-9dbf-dae8429c667f	9933b355-d93d-4bed-87d8-3595fc72ee00	2026-03-01 15:44:07.511947	\N
445047b2-c21a-4325-9860-d7197fc3beaf	568d17ae-20ee-438c-b1d1-1afdb0a26bc6	a10cceed-9994-40f9-97f8-b85da58309c9	2026-03-01 15:44:07.5178	\N
e531d782-197c-4bda-b933-900087ebfce8	568d17ae-20ee-438c-b1d1-1afdb0a26bc6	c1f876b7-82be-4652-b49e-e29f93418adf	2026-03-01 15:44:07.51879	\N
043e0978-6c8e-4d54-a732-9b9e622a3f72	568d17ae-20ee-438c-b1d1-1afdb0a26bc6	5feb4705-3e15-41f0-abe9-54a687cb8378	2026-03-01 15:44:07.519786	\N
7a855c1e-cf23-4b82-9052-cdf1dcbf0c47	568d17ae-20ee-438c-b1d1-1afdb0a26bc6	a429e651-676d-470a-b78e-72387bd23921	2026-03-01 15:44:07.521788	\N
b4e306fb-6e3d-4831-8243-d936588a59de	568d17ae-20ee-438c-b1d1-1afdb0a26bc6	97ba4968-c723-4599-9615-849f6da31eae	2026-03-01 15:44:07.523799	\N
77ee8643-7a68-4a52-8c3c-0f5adbadc62f	568d17ae-20ee-438c-b1d1-1afdb0a26bc6	619b5ea4-4839-40ff-88c2-05c940ff3b15	2026-03-01 15:44:07.524798	\N
ba35f976-f5b4-43c0-a32d-bc7f022dc0ff	568d17ae-20ee-438c-b1d1-1afdb0a26bc6	fc27a1d1-6ef5-484e-b32b-47f5f3d7e81c	2026-03-01 15:44:07.525789	\N
ef143d57-17d1-4239-b330-4f79f2a84456	568d17ae-20ee-438c-b1d1-1afdb0a26bc6	0ec6ee5f-2ffa-4dda-9fc4-3162eb855547	2026-03-01 15:44:07.526804	\N
e1766659-94b0-4a32-bcf8-d5886c798997	8e25c438-70a5-4d9b-8634-9f16ab2cb1f3	84f95820-f480-4b44-af1b-cbffc5175f0c	2026-04-03 21:46:38.760446	\N
379226b4-0d74-407b-a140-cb6415817b34	63ad1a14-2623-4287-9dbf-dae8429c667f	84f95820-f480-4b44-af1b-cbffc5175f0c	2026-04-03 21:46:38.760446	\N
4cf33989-afd3-46e1-be16-ec7b37c818e3	568d17ae-20ee-438c-b1d1-1afdb0a26bc6	84f95820-f480-4b44-af1b-cbffc5175f0c	2026-04-03 21:46:38.760446	\N
5cbe77ec-f7a8-482a-bb75-0937c1acb011	8e25c438-70a5-4d9b-8634-9f16ab2cb1f3	23347b45-c1a6-4a70-babe-4961753f2b94	2026-04-03 21:46:38.760446	\N
f3ac8f17-79e0-4c51-bd6a-a4d32126d7d0	63ad1a14-2623-4287-9dbf-dae8429c667f	23347b45-c1a6-4a70-babe-4961753f2b94	2026-04-03 21:46:38.760446	\N
e98f5a6e-44b1-4a95-9432-fbb09480bb12	568d17ae-20ee-438c-b1d1-1afdb0a26bc6	23347b45-c1a6-4a70-babe-4961753f2b94	2026-04-03 21:46:38.760446	\N
ee6d0f93-7bda-4a47-a2e7-b947035231d6	8e25c438-70a5-4d9b-8634-9f16ab2cb1f3	c0ec87ac-7c49-4782-866c-3905ed2fc201	2026-04-03 21:46:38.760446	\N
a6ce2f9c-ed82-408d-a16b-1699f40e5db4	63ad1a14-2623-4287-9dbf-dae8429c667f	c0ec87ac-7c49-4782-866c-3905ed2fc201	2026-04-03 21:46:38.760446	\N
6b03f882-cedd-467c-8bd3-642182257457	568d17ae-20ee-438c-b1d1-1afdb0a26bc6	c0ec87ac-7c49-4782-866c-3905ed2fc201	2026-04-03 21:46:38.760446	\N
4d73a16b-b32e-4d44-8a51-749acf0ba2bb	8e25c438-70a5-4d9b-8634-9f16ab2cb1f3	2eaa594f-97e8-4074-a017-19cf390ea9f5	2026-04-03 21:46:38.760446	\N
18b25b1a-ad18-4e67-9af2-0a339f5eb516	63ad1a14-2623-4287-9dbf-dae8429c667f	2eaa594f-97e8-4074-a017-19cf390ea9f5	2026-04-03 21:46:38.760446	\N
31c466cb-3a12-463c-aea7-91c8938a0e0e	568d17ae-20ee-438c-b1d1-1afdb0a26bc6	2eaa594f-97e8-4074-a017-19cf390ea9f5	2026-04-03 21:46:38.760446	\N
a6760697-1251-4570-9663-e124ccd5cab5	8e25c438-70a5-4d9b-8634-9f16ab2cb1f3	d281c5cd-c555-4caa-89fd-cad172a26f05	2026-04-03 21:46:38.760446	\N
90a61db4-03c3-433f-9f2c-19e324027c36	63ad1a14-2623-4287-9dbf-dae8429c667f	d281c5cd-c555-4caa-89fd-cad172a26f05	2026-04-03 21:46:38.760446	\N
d6e93f83-7318-4e50-9d14-2610b4e6c1f4	568d17ae-20ee-438c-b1d1-1afdb0a26bc6	d281c5cd-c555-4caa-89fd-cad172a26f05	2026-04-03 21:46:38.760446	\N
e7ae3cb3-322f-4c8a-9aad-4091468332e2	8e25c438-70a5-4d9b-8634-9f16ab2cb1f3	9e4afcc1-f089-4a6d-8d84-2973c83ab579	2026-04-03 21:46:38.760446	\N
7d9457c7-f3e2-463e-9923-41f09d98ffcc	63ad1a14-2623-4287-9dbf-dae8429c667f	9e4afcc1-f089-4a6d-8d84-2973c83ab579	2026-04-03 21:46:38.760446	\N
4cf82173-02ee-4c35-8db5-4a941d232452	568d17ae-20ee-438c-b1d1-1afdb0a26bc6	9e4afcc1-f089-4a6d-8d84-2973c83ab579	2026-04-03 21:46:38.760446	\N
7edfcbb0-a9c5-4dfa-ad76-a49d3d2ade76	8e25c438-70a5-4d9b-8634-9f16ab2cb1f3	461a45c2-68f6-4a59-8259-8e91e0533195	2026-04-03 21:46:38.760446	\N
1b297da9-d4b2-48e8-99c3-2cde8736c6d6	63ad1a14-2623-4287-9dbf-dae8429c667f	461a45c2-68f6-4a59-8259-8e91e0533195	2026-04-03 21:46:38.760446	\N
d7ac93d4-cd13-4977-9216-dd47cb78b961	568d17ae-20ee-438c-b1d1-1afdb0a26bc6	461a45c2-68f6-4a59-8259-8e91e0533195	2026-04-03 21:46:38.760446	\N
aa2e9c7f-1e54-4358-9dd6-c6656c9a44dc	8e25c438-70a5-4d9b-8634-9f16ab2cb1f3	e47a4689-2037-4f69-b9e0-ff0b0703969f	2026-04-03 21:46:38.760446	\N
45d15e17-c11d-44c1-8be8-082cb911be00	63ad1a14-2623-4287-9dbf-dae8429c667f	e47a4689-2037-4f69-b9e0-ff0b0703969f	2026-04-03 21:46:38.760446	\N
875fb6af-fece-4a54-ab30-6111b3a4580f	568d17ae-20ee-438c-b1d1-1afdb0a26bc6	e47a4689-2037-4f69-b9e0-ff0b0703969f	2026-04-03 21:46:38.760446	\N
2a775ecb-5262-499a-a0c3-487834037907	8e25c438-70a5-4d9b-8634-9f16ab2cb1f3	3197647a-a499-4817-8c47-1ef19da51ff2	2026-04-03 21:46:38.760446	\N
00ac0d6b-6bef-4d9c-9cf0-8c86da3eefc8	63ad1a14-2623-4287-9dbf-dae8429c667f	3197647a-a499-4817-8c47-1ef19da51ff2	2026-04-03 21:46:38.760446	\N
92ccb37b-dac8-4de0-bd93-e3e4a6b55220	568d17ae-20ee-438c-b1d1-1afdb0a26bc6	3197647a-a499-4817-8c47-1ef19da51ff2	2026-04-03 21:46:38.760446	\N
7813d2a8-5680-4f74-ba9d-942f42d5f2fe	8e25c438-70a5-4d9b-8634-9f16ab2cb1f3	02ee7a8c-8dc5-4462-9b41-470c79fcc671	2026-04-03 21:46:38.760446	\N
b3d875bb-0266-44e7-88c1-d50c5d094471	63ad1a14-2623-4287-9dbf-dae8429c667f	02ee7a8c-8dc5-4462-9b41-470c79fcc671	2026-04-03 21:46:38.760446	\N
d21ebbc0-e65d-4c4d-9c8e-541201d51920	568d17ae-20ee-438c-b1d1-1afdb0a26bc6	02ee7a8c-8dc5-4462-9b41-470c79fcc671	2026-04-03 21:46:38.760446	\N
c914b888-c2bf-49af-8ac2-249ea0d78dc6	8e25c438-70a5-4d9b-8634-9f16ab2cb1f3	4199df10-1c1d-422b-9719-daff98fa21b6	2026-04-03 21:46:38.760446	\N
92b05fee-91e6-450a-90d5-02a14fcbceff	63ad1a14-2623-4287-9dbf-dae8429c667f	4199df10-1c1d-422b-9719-daff98fa21b6	2026-04-03 21:46:38.760446	\N
5dd18248-c4c3-47c0-be1e-7355aa013d6d	568d17ae-20ee-438c-b1d1-1afdb0a26bc6	4199df10-1c1d-422b-9719-daff98fa21b6	2026-04-03 21:46:38.760446	\N
46bd2857-fa42-4451-a91a-171d5d1e0efc	d3e8bb4a-d6e2-49d5-80b9-ce47d1d2af92	5805e19e-c3e7-4086-bd7a-6a963539ef5e	2026-04-03 21:48:31.231572	0bc9c5f7-dc77-4f7d-bfbf-4b347a934b24
ba28cb8a-7b85-4b1e-ab74-c9641bb729b4	d3e8bb4a-d6e2-49d5-80b9-ce47d1d2af92	50303ba1-ca2c-491d-81b8-8b95e436c9da	2026-04-03 21:48:31.231581	0bc9c5f7-dc77-4f7d-bfbf-4b347a934b24
b40e5dbd-4b8b-4d01-9314-05ab58519c88	d3e8bb4a-d6e2-49d5-80b9-ce47d1d2af92	8662b74a-6abe-45a5-b2c7-98f621d8320a	2026-04-03 21:48:31.231586	0bc9c5f7-dc77-4f7d-bfbf-4b347a934b24
c6f8d6a9-1c20-476d-83ef-d5108185968e	d3e8bb4a-d6e2-49d5-80b9-ce47d1d2af92	5908338f-ddd4-4683-ac52-f8d7ceb897a1	2026-04-03 21:48:31.23159	0bc9c5f7-dc77-4f7d-bfbf-4b347a934b24
32e32a0f-9a0c-4daa-8b92-efe8ce1b1599	d3e8bb4a-d6e2-49d5-80b9-ce47d1d2af92	2511d363-1467-4683-9fb7-aec385271e03	2026-04-03 21:48:31.231594	0bc9c5f7-dc77-4f7d-bfbf-4b347a934b24
54696eec-a592-4600-9f64-fefe44b9c2d5	d3e8bb4a-d6e2-49d5-80b9-ce47d1d2af92	898e3a3b-54e7-49a4-adff-a02e09a04800	2026-04-03 21:48:31.231598	0bc9c5f7-dc77-4f7d-bfbf-4b347a934b24
1aa311cc-d149-41c8-afed-d011c8d93c42	d3e8bb4a-d6e2-49d5-80b9-ce47d1d2af92	461a45c2-68f6-4a59-8259-8e91e0533195	2026-04-03 21:48:31.231603	0bc9c5f7-dc77-4f7d-bfbf-4b347a934b24
2297f420-9c65-4448-abe9-83b618371f63	d3e8bb4a-d6e2-49d5-80b9-ce47d1d2af92	e47a4689-2037-4f69-b9e0-ff0b0703969f	2026-04-03 21:48:31.231607	0bc9c5f7-dc77-4f7d-bfbf-4b347a934b24
e9df57bf-ef8f-45a5-b84c-210493bc8f46	d3e8bb4a-d6e2-49d5-80b9-ce47d1d2af92	3197647a-a499-4817-8c47-1ef19da51ff2	2026-04-03 21:48:31.231611	0bc9c5f7-dc77-4f7d-bfbf-4b347a934b24
9869147d-85d2-4e41-917e-d10eae91e3d0	d3e8bb4a-d6e2-49d5-80b9-ce47d1d2af92	02ee7a8c-8dc5-4462-9b41-470c79fcc671	2026-04-03 21:48:31.231615	0bc9c5f7-dc77-4f7d-bfbf-4b347a934b24
ce6ac438-a0d3-42f9-83c1-4788b18acd57	d3e8bb4a-d6e2-49d5-80b9-ce47d1d2af92	4199df10-1c1d-422b-9719-daff98fa21b6	2026-04-03 21:48:31.23162	0bc9c5f7-dc77-4f7d-bfbf-4b347a934b24
7b8b289e-0b23-4528-b15e-12cf2887cddf	d4670a58-1d8a-4ced-966b-e32ed9b37037	02ee7a8c-8dc5-4462-9b41-470c79fcc671	2026-04-03 21:48:47.559468	0bc9c5f7-dc77-4f7d-bfbf-4b347a934b24
b3f8afb3-2950-471c-b9ec-f296285e7af0	d4670a58-1d8a-4ced-966b-e32ed9b37037	4199df10-1c1d-422b-9719-daff98fa21b6	2026-04-03 21:48:47.559476	0bc9c5f7-dc77-4f7d-bfbf-4b347a934b24
\.


--
-- Data for Name: roles; Type: TABLE DATA; Schema: public; Owner: postgres
--

COPY public.roles (role_id, role_name, role_code, description, is_active, is_system, created_at, updated_at, created_by, updated_by) FROM stdin;
8e25c438-70a5-4d9b-8634-9f16ab2cb1f3	超级管理员	super_admin	系统超级管理员，拥有所有权限	t	t	2026-02-25 08:26:52.243327	2026-02-25 08:26:52.243327	\N	\N
63ad1a14-2623-4287-9dbf-dae8429c667f	系统管理员	system_admin	系统管理员，负责系统配置和用户管理	t	f	2026-02-25 08:26:52.243327	2026-02-25 10:44:06.367925	\N	\N
568d17ae-20ee-438c-b1d1-1afdb0a26bc6	安全管理员	security_admin	安全管理员，负责安全组件和证书管理	t	f	2026-02-25 08:26:52.243327	2026-02-25 10:44:06.367925	\N	\N
d3e8bb4a-d6e2-49d5-80b9-ce47d1d2af92	交易员	trader	交易员，负责交易操作	t	f	2026-02-25 08:26:52.243327	2026-02-25 10:44:06.367925	\N	\N
d4670a58-1d8a-4ced-966b-e32ed9b37037	观察员	observer	观察员，仅查看权限	t	f	2026-02-25 08:26:52.243327	2026-02-25 10:44:06.367925	\N	\N
\.


--
-- Data for Name: security_component_logs; Type: TABLE DATA; Schema: public; Owner: postgres
--

COPY public.security_component_logs (log_id, component_id, action, old_config, new_config, result, error_message, performed_by, performed_at, ip_address) FROM stdin;
aa038091-959e-4cf5-9071-04b5c58c668f	ace80f1b-a88e-4e80-b195-9105eb9f8685	disable	{"key_versions": 3, "rotation_days": 90, "rotation_enabled": false}	{"key_versions": 3, "rotation_days": 90, "rotation_enabled": false}	success	\N	\N	2026-02-25 09:57:09.716955	127.0.0.1
ec931fd7-05b5-41ff-9195-2fcfde681ffc	ace80f1b-a88e-4e80-b195-9105eb9f8685	enable	{"key_versions": 3, "rotation_days": 90, "rotation_enabled": false}	{"key_versions": 3, "rotation_days": 90, "rotation_enabled": false}	success	\N	\N	2026-02-25 09:57:11.020197	127.0.0.1
9ce902b1-98d1-40b8-b51a-f06f2dd203ca	91aeec05-0717-4e31-9f39-913b8d2e0fe2	enable	{"log_queries": false, "alert_threshold": 5, "detect_injection": true}	{"log_queries": false, "alert_threshold": 5, "detect_injection": true}	success	\N	\N	2026-02-25 10:12:20.34467	127.0.0.1
b130ce45-693b-45c2-bdfd-74726a0e6b61	8a34b422-3575-4408-9b16-793ecae5e1ee	enable	{"token_length": 32, "cookie_secure": true, "expire_minutes": 60}	{"token_length": 32, "cookie_secure": true, "expire_minutes": 60}	success	\N	\N	2026-02-25 10:12:26.744577	127.0.0.1
a98d9d11-97ec-46e9-abbd-c864ee9212f6	0b0e7243-901d-4014-b4ce-a17583da7a62	enable	{"require_token": true, "heartbeat_interval": 30, "max_connections_per_user": 5}	{"require_token": true, "heartbeat_interval": 30, "max_connections_per_user": 5}	success	\N	\N	2026-02-25 10:12:30.274249	127.0.0.1
dc3cc608-6591-4bd1-8b30-43aa9a0ce1c5	662c851f-7cf8-4c54-bc20-e1bbe8113977	enable	{"algorithm": "HMAC-SHA256", "nonce_required": true, "timestamp_tolerance": 300}	{"algorithm": "HMAC-SHA256", "nonce_required": true, "timestamp_tolerance": 300}	success	\N	\N	2026-02-25 10:12:33.486348	127.0.0.1
d0aa5d20-3cbd-4109-aa45-c3286dc38012	6cbfa72b-f621-4bee-bd5a-563b30b53716	enable	{"mask_char": "*", "mask_patterns": ["password", "api_key", "secret", "token"]}	{"mask_char": "*", "mask_patterns": ["password", "api_key", "secret", "token"]}	success	\N	\N	2026-02-25 10:12:40.088735	127.0.0.1
ea6f4a03-6678-4f4a-b869-e0644e10bc30	816e9640-a453-4586-b822-4db30e4700e5	enable	{"auto_update": false, "scan_interval_days": 7, "alert_on_vulnerability": true}	{"auto_update": false, "scan_interval_days": 7, "alert_on_vulnerability": true}	success	\N	\N	2026-02-25 10:12:47.132093	127.0.0.1
9a14b42b-f6a0-4d3d-9b9a-52e1f755c581	5db2e69a-db39-4e6c-98fa-e4f0ee361c19	enable	{"header_name": "X-Request-ID", "log_requests": true, "track_performance": true}	{"header_name": "X-Request-ID", "log_requests": true, "track_performance": true}	success	\N	\N	2026-02-25 10:12:52.128831	127.0.0.1
6807f251-8095-49c3-8f15-95f6b844933d	4efa5b2b-ce63-44e3-9da4-92dad80fcd97	disable	{"algorithm": "HS256", "expire_minutes": 30, "refresh_expire_days": 7}	{"algorithm": "HS256", "expire_minutes": 30, "refresh_expire_days": 7}	success	\N	0bc9c5f7-dc77-4f7d-bfbf-4b347a934b24	2026-04-03 22:19:07.36349	103.97.2.29
8a552593-58af-4740-af1d-ac74baf12981	0026291b-75be-4dd1-8e0d-b5b980e83abd	disable	{"rounds": 12, "salt_rounds": 12}	{"rounds": 12, "salt_rounds": 12}	success	\N	0bc9c5f7-dc77-4f7d-bfbf-4b347a934b24	2026-04-03 22:19:22.787477	103.97.2.29
5ef10bdf-aa6a-4a6c-b3d0-5779b23c24ea	4efa5b2b-ce63-44e3-9da4-92dad80fcd97	enable	{"algorithm": "HS256", "expire_minutes": 30, "refresh_expire_days": 7}	{"algorithm": "HS256", "expire_minutes": 30, "refresh_expire_days": 7}	success	\N	0bc9c5f7-dc77-4f7d-bfbf-4b347a934b24	2026-04-03 22:24:21.169076	127.0.0.1
a667484d-98f7-435f-9bb7-231f3202c13c	4efa5b2b-ce63-44e3-9da4-92dad80fcd97	disable	{"algorithm": "HS256", "expire_minutes": 30, "refresh_expire_days": 7}	{"algorithm": "HS256", "expire_minutes": 30, "refresh_expire_days": 7}	success	\N	0bc9c5f7-dc77-4f7d-bfbf-4b347a934b24	2026-04-03 22:24:21.21497	127.0.0.1
e003dd91-8e35-4f16-9b01-17f3e1819311	4efa5b2b-ce63-44e3-9da4-92dad80fcd97	enable	{"algorithm": "HS256", "expire_minutes": 30, "refresh_expire_days": 7}	{"algorithm": "HS256", "expire_minutes": 30, "refresh_expire_days": 7}	success	\N	0bc9c5f7-dc77-4f7d-bfbf-4b347a934b24	2026-04-03 22:26:40.705967	103.97.2.29
ceae9afa-16f8-4916-bf6e-fa11b4991593	0026291b-75be-4dd1-8e0d-b5b980e83abd	enable	{"rounds": 12, "salt_rounds": 12}	{"rounds": 12, "salt_rounds": 12}	success	\N	0bc9c5f7-dc77-4f7d-bfbf-4b347a934b24	2026-04-03 22:26:42.497274	103.97.2.29
ad535057-9d9b-4434-b313-262e6b8880a6	b5bae439-dfa7-470a-8840-ab75a5bc2b4c	enable	{"whitelist": [], "block_mode": "deny", "enabled_paths": ["/api/v1/admin/*"]}	{"whitelist": [], "block_mode": "deny", "enabled_paths": ["/api/v1/admin/*"]}	success	\N	0bc9c5f7-dc77-4f7d-bfbf-4b347a934b24	2026-04-03 22:26:45.264971	103.97.2.29
08ad3bfe-92cd-4e0c-aafa-785dad563245	b5bae439-dfa7-470a-8840-ab75a5bc2b4c	disable	{"whitelist": [], "block_mode": "deny", "enabled_paths": ["/api/v1/admin/*"]}	{"whitelist": [], "block_mode": "deny", "enabled_paths": ["/api/v1/admin/*"]}	success	\N	0bc9c5f7-dc77-4f7d-bfbf-4b347a934b24	2026-04-03 22:26:47.00469	103.97.2.29
\.


--
-- Data for Name: security_components; Type: TABLE DATA; Schema: public; Owner: postgres
--

COPY public.security_components (component_id, component_code, component_name, component_type, description, is_enabled, config_json, priority, status, last_check_at, error_message, created_at, updated_at, created_by, updated_by) FROM stdin;
e3008c90-a916-4ea0-8864-a80558a511b7	rate_limiting	速率限制	middleware	API 请求速率限制，防止暴力攻击和资源滥用	t	{"burst": 20, "by_ip": true, "requests_per_minute": 100}	80	active	2026-02-25 10:04:26.172693	\N	2026-02-25 09:36:19.421277	2026-02-25 10:04:26.17048	\N	\N
ace80f1b-a88e-4e80-b195-9105eb9f8685	key_management	密钥管理机制	service	集中管理系统密钥，支持密钥轮换和版本控制	t	{"key_versions": 3, "rotation_days": 90, "rotation_enabled": false}	70	active	2026-02-25 10:04:26.177696	\N	2026-02-25 09:36:19.421277	2026-02-25 10:04:26.177269	\N	\N
9f351a68-4ca1-4668-abf0-02acdbefa6cb	input_validation	Pydantic 输入验证	service	使用 Pydantic 进行请求数据验证和类型检查	t	{"strict_mode": true, "validate_assignment": true}	75	active	2026-02-25 10:04:26.183693	\N	2026-02-25 09:36:19.421277	2026-02-25 10:04:26.181812	\N	\N
4c209434-83ec-4af7-b927-103af35b260d	api_key_encryption	API 密钥加密存储	service	对交易所 API 密钥进行加密存储，使用 AES-256 加密算法	t	{"algorithm": "AES-256-GCM", "key_rotation_days": 90}	90	active	2026-02-25 10:04:26.748348	\N	2026-02-25 09:36:19.421277	2026-02-25 10:04:26.747903	\N	\N
474bc7dd-9dd6-4c9d-b98e-ae73c317659f	cors_protection	CORS 跨域保护	middleware	限制跨域请求来源，防止未授权的跨域访问	t	{"max_age": 3600, "allowed_origins": ["http://localhost:3000", "http://13.115.21.77:3000"], "allow_credentials": true}	85	active	2026-02-25 10:04:26.751349	\N	2026-02-25 09:36:19.421277	2026-02-25 10:04:26.751717	\N	\N
91aeec05-0717-4e31-9f39-913b8d2e0fe2	sql_audit	SQL 查询安全审计	protection	审计和监控 SQL 查询，防止 SQL 注入攻击	t	{"log_queries": false, "alert_threshold": 5, "detect_injection": true}	65	active	2026-02-25 10:12:20.34467	\N	2026-02-25 09:36:19.421277	2026-02-25 10:12:20.342372	\N	\N
8a34b422-3575-4408-9b16-793ecae5e1ee	csrf_protection	CSRF 跨站请求伪造保护	middleware	防止跨站请求伪造攻击，验证请求来源	t	{"token_length": 32, "cookie_secure": true, "expire_minutes": 60}	60	active	2026-02-25 10:12:26.735967	\N	2026-02-25 09:36:19.421277	2026-02-25 10:12:26.741757	\N	\N
0b0e7243-901d-4014-b4ce-a17583da7a62	websocket_auth	WebSocket 连接认证	middleware	WebSocket 连接的身份验证和授权机制	t	{"require_token": true, "heartbeat_interval": 30, "max_connections_per_user": 5}	55	active	2026-02-25 10:12:30.258529	\N	2026-02-25 09:36:19.421277	2026-02-25 10:12:30.270124	\N	\N
662c851f-7cf8-4c54-bc20-e1bbe8113977	request_signing	请求签名验证	middleware	API 请求签名机制，防止请求篡改和重放攻击	t	{"algorithm": "HMAC-SHA256", "nonce_required": true, "timestamp_tolerance": 300}	50	active	2026-02-25 10:12:33.470685	\N	2026-02-25 09:36:19.421277	2026-02-25 10:12:33.481979	\N	\N
6cbfa72b-f621-4bee-bd5a-563b30b53716	log_sanitization	日志脱敏处理	service	自动脱敏日志中的敏感信息（密码、密钥、个人信息等）	t	{"mask_char": "*", "mask_patterns": ["password", "api_key", "secret", "token"]}	45	active	2026-02-25 10:12:40.079634	\N	2026-02-25 09:36:19.421277	2026-02-25 10:12:40.086307	\N	\N
37fb118e-016d-4022-82ea-27c5ec9f0c93	backup_recovery	数据备份恢复	service	自动备份数据库和关键配置文件，支持快速恢复	f	{"encrypt_backup": true, "retention_days": 30, "backup_location": "/backups", "backup_interval_hours": 24}	25	inactive	\N	\N	2026-02-25 09:36:19.421277	2026-02-25 09:36:40.067123	\N	\N
bb09d622-5843-49e4-8a7f-3797d01d5435	secret_key_rotation	SECRET_KEY 轮换	service	定期更换系统 SECRET_KEY，增强安全性	f	{"key_strength": 256, "current_key_age_days": 0, "rotation_interval_days": 90}	20	inactive	\N	\N	2026-02-25 09:36:19.421277	2026-02-25 09:36:40.067123	\N	\N
816e9640-a453-4586-b822-4db30e4700e5	dependency_scan	依赖安全扫描	service	定期扫描项目依赖的安全漏洞	t	{"auto_update": false, "scan_interval_days": 7, "alert_on_vulnerability": true}	30	active	2026-02-25 10:12:47.132093	\N	2026-02-25 09:36:19.421277	2026-02-25 10:12:47.137093	\N	\N
5db2e69a-db39-4e6c-98fa-e4f0ee361c19	request_tracking	请求追踪系统	middleware	为每个请求生成唯一 ID，追踪请求链路和性能	t	{"header_name": "X-Request-ID", "log_requests": true, "track_performance": true}	35	active	2026-02-25 10:12:52.128831	\N	2026-02-25 09:36:19.421277	2026-02-25 10:12:52.134295	\N	\N
4efa5b2b-ce63-44e3-9da4-92dad80fcd97	jwt_auth	JWT Token 认证	middleware	JSON Web Token 身份认证机制，用于API请求的用户身份验证	t	{"algorithm": "HS256", "expire_minutes": 30, "refresh_expire_days": 7}	100	active	2026-04-03 22:26:40.700781	\N	2026-02-25 09:36:19.421277	2026-04-03 22:26:40.699949	\N	0bc9c5f7-dc77-4f7d-bfbf-4b347a934b24
0026291b-75be-4dd1-8e0d-b5b980e83abd	bcrypt_hash	密码 Bcrypt 哈希	service	使用 bcrypt 算法对用户密码进行安全哈希存储	t	{"rounds": 12, "salt_rounds": 12}	95	active	2026-04-03 22:26:42.489951	\N	2026-02-25 09:36:19.421277	2026-04-03 22:26:42.489108	\N	0bc9c5f7-dc77-4f7d-bfbf-4b347a934b24
b5bae439-dfa7-470a-8840-ab75a5bc2b4c	ip_whitelist	IP 白名单控制	protection	限制只允许白名单内的 IP 地址访问敏感接口	f	{"whitelist": [], "block_mode": "deny", "enabled_paths": ["/api/v1/admin/*"]}	40	inactive	2026-04-03 22:26:46.999275	\N	2026-02-25 09:36:19.421277	2026-04-03 22:26:46.998518	\N	0bc9c5f7-dc77-4f7d-bfbf-4b347a934b24
\.


--
-- Data for Name: spread_records; Type: TABLE DATA; Schema: public; Owner: postgres
--

COPY public.spread_records (id, symbol, binance_bid, binance_ask, bybit_bid, bybit_ask, forward_spread, reverse_spread, "timestamp") FROM stdin;
\.


--
-- Data for Name: ssl_certificate_logs; Type: TABLE DATA; Schema: public; Owner: postgres
--

COPY public.ssl_certificate_logs (log_id, cert_id, action, result, error_message, performed_by, performed_at, ip_address) FROM stdin;
\.


--
-- Data for Name: ssl_certificates; Type: TABLE DATA; Schema: public; Owner: postgres
--

COPY public.ssl_certificates (cert_id, cert_name, domain_name, cert_type, cert_file_path, key_file_path, chain_file_path, issuer, subject, serial_number, issued_at, expires_at, status, is_deployed, auto_renew, days_before_expiry, last_check_at, created_at, updated_at, uploaded_by) FROM stdin;
bb8f607f-e762-4af4-82e0-a1e479a570d1	go.hustle2026.xyz - Lets Encrypt	go.hustle2026.xyz	letsencrypt	/etc/letsencrypt/live/go.hustle2026.xyz/fullchain.pem	/etc/letsencrypt/live/go.hustle2026.xyz/privkey.pem	/etc/letsencrypt/live/go.hustle2026.xyz/chain.pem	Lets Encrypt	go.hustle2026.xyz	\N	2026-03-21 08:22:52.563976	2026-06-19 00:00:00	active	t	t	\N	\N	2026-03-21 08:22:52.563976	2026-03-21 08:22:52.563976	\N
49185790-d7a7-48fd-98a5-d73e5f07c13e	www.hustle2026.xyz - Lets Encrypt	www.hustle2026.xyz	letsencrypt	/etc/letsencrypt/live/www.hustle2026.xyz/fullchain.pem	/etc/letsencrypt/live/www.hustle2026.xyz/privkey.pem	/etc/letsencrypt/live/www.hustle2026.xyz/chain.pem	Lets Encrypt	www.hustle2026.xyz	\N	2026-03-19 19:01:56	2026-06-17 19:01:56	active	t	t	\N	\N	2026-03-21 08:24:50.956564	2026-03-21 08:24:50.956564	\N
85425922-3609-4a32-b477-9160b47c88a6	admin.hustle2026.xyz - Lets Encrypt	admin.hustle2026.xyz	letsencrypt	/etc/letsencrypt/live/admin.hustle2026.xyz/fullchain.pem	/etc/letsencrypt/live/admin.hustle2026.xyz/privkey.pem	\N	\N	\N	\N	2026-03-20 22:16:44.131137	2026-06-18 22:16:44.131137	active	f	t	\N	\N	2026-04-03 22:16:44.131137	2026-04-03 22:16:44.131137	\N
\.


--
-- Data for Name: strategies; Type: TABLE DATA; Schema: public; Owner: postgres
--

COPY public.strategies (id, user_id, name, symbol, direction, min_spread, status, params, created_at, updated_at) FROM stdin;
\.


--
-- Data for Name: strategy_configs; Type: TABLE DATA; Schema: public; Owner: postgres
--

COPY public.strategy_configs (config_id, user_id, strategy_type, target_spread, order_qty, retry_times, mt5_stuck_threshold, is_enabled, create_time, update_time, opening_sync_count, closing_sync_count, m_coin, ladders, opening_m_coin, closing_m_coin, trigger_check_interval, opening_trigger_check_interval, closing_trigger_check_interval) FROM stdin;
aa0ba1ff-ae2c-4df6-bbf9-a42442bccac5	0bc9c5f7-dc77-4f7d-bfbf-4b347a934b24	reverse	1	1	3	5	f	2026-02-26 11:19:02.659948	2026-03-03 09:26:10.332652	2	2	1	[{"enabled": true, "qtyLimit": 1.0, "openPrice": 1.8, "threshold": 2.0}]	1	1	0.5	0.5	0.5
a84bb13f-6861-42eb-be66-e35fb183b7a1	0bc9c5f7-dc77-4f7d-bfbf-4b347a934b24	forward	1	1	3	5	f	2026-02-22 16:40:03.849973	2026-03-06 13:58:49.648153	3	1	1	[{"enabled": true, "qtyLimit": 1.0, "openPrice": 2.8, "threshold": 1.0}]	1	1	0.5	0.5	0.5
3e47594b-2836-460a-9f9f-bde1f79efa9b	66764cd6-d1c9-4468-a478-85b526a16927	reverse	1	1	3	5	f	2026-02-20 16:40:51.243939	2026-03-22 22:52:53.192512	3	3	5	[{"enabled": true, "qtyLimit": 3, "openPrice": 3, "threshold": 2}]	5	5	0.5	0.5	0.5
7c67e5c4-bd3b-4abe-a82a-82c27479d7a3	66764cd6-d1c9-4468-a478-85b526a16927	forward	1	1	3	5	f	2026-03-22 22:52:00.752361	2026-03-22 22:52:55.81722	3	3	5	[{"enabled": true, "qtyLimit": 3, "openPrice": 3, "threshold": 2}]	5	5	0.5	0.5	0.5
\.


--
-- Data for Name: strategy_performance; Type: TABLE DATA; Schema: public; Owner: postgres
--

COPY public.strategy_performance (performance_id, strategy_id, today_trades, today_profit, total_trades, total_profit, win_rate, max_drawdown, date, "timestamp") FROM stdin;
\.


--
-- Data for Name: strategy_timing_configs; Type: TABLE DATA; Schema: public; Owner: postgres
--

COPY public.strategy_timing_configs (id, config_level, strategy_type, strategy_instance_id, trigger_check_interval, opening_trigger_count, closing_trigger_count, binance_timeout, bybit_timeout, order_check_interval, spread_check_interval, mt5_deal_sync_wait, api_spam_prevention_delay, delayed_single_leg_check_delay, delayed_single_leg_second_check_delay, api_retry_times, api_retry_delay, max_binance_limit_retries, open_wait_after_cancel_no_trade, open_wait_after_cancel_part, close_wait_after_cancel_no_trade, close_wait_after_cancel_part, status_polling_interval, debounce_delay, template, is_locked, locked_by, locked_at, created_at, updated_at, created_by) FROM stdin;
1	global	\N	\N	0.5	3	3	5	0.1	0.2	2	3	3	10	1	3	0.5	25	3	2	3	2	5	0.5	\N	f	\N	\N	2026-03-24 12:59:50.750453	2026-03-24 12:59:50.750453	\N
2	strategy_type	forward_opening	\N	0.5	3	3	5	0.1	0.2	2	3	3	10	1	3	0.5	25	3	2	3	2	5	0.5	balanced	f	\N	\N	2026-04-03 16:48:11.257058	2026-04-03 17:24:09.735066	0bc9c5f7-dc77-4f7d-bfbf-4b347a934b24
4	strategy_type	forward_closing	\N	0.5	3	3	5	0.1	0.2	2	3	3	10	1	3	0.5	25	3	2	3	2	5	0.5	\N	f	\N	\N	2026-04-03 17:26:07.521451	2026-04-03 17:26:07.521451	0bc9c5f7-dc77-4f7d-bfbf-4b347a934b24
\.


--
-- Data for Name: system_alerts; Type: TABLE DATA; Schema: public; Owner: postgres
--

COPY public.system_alerts (alert_id, user_id, alert_type, severity, title, message, is_read, "timestamp") FROM stdin;
\.


--
-- Data for Name: system_logs; Type: TABLE DATA; Schema: public; Owner: postgres
--

COPY public.system_logs (log_id, user_id, level, category, message, details, "timestamp") FROM stdin;
\.


--
-- Data for Name: timing_config_history; Type: TABLE DATA; Schema: public; Owner: postgres
--

COPY public.timing_config_history (id, config_id, config_level, strategy_type, strategy_instance_id, config_data, template, created_at, created_by, change_reason) FROM stdin;
1	2	strategy_type	forward_opening	\N	{"bybit_timeout": 0.1, "debounce_delay": 0.5, "api_retry_delay": 0.5, "api_retry_times": 3, "binance_timeout": 5.0, "mt5_deal_sync_wait": 3.0, "order_check_interval": 0.2, "closing_trigger_count": 3, "opening_trigger_count": 3, "spread_check_interval": 2.0, "trigger_check_interval": 0.5, "status_polling_interval": 5.0, "api_spam_prevention_delay": 3.0, "max_binance_limit_retries": 25, "open_wait_after_cancel_part": 2.0, "close_wait_after_cancel_part": 2.0, "delayed_single_leg_check_delay": 10.0, "open_wait_after_cancel_no_trade": 3.0, "close_wait_after_cancel_no_trade": 3.0, "delayed_single_leg_second_check_delay": 1.0}	\N	2026-04-03 16:48:35.96376	0bc9c5f7-dc77-4f7d-bfbf-4b347a934b24	\N
2	2	strategy_type	forward_opening	\N	{"bybit_timeout": 0.1, "debounce_delay": 0.5, "api_retry_delay": 0.5, "api_retry_times": 3, "binance_timeout": 5.0, "mt5_deal_sync_wait": 3.0, "order_check_interval": 0.2, "closing_trigger_count": 3, "opening_trigger_count": 3, "spread_check_interval": 2.0, "trigger_check_interval": 0.5, "status_polling_interval": 5.0, "api_spam_prevention_delay": 3.0, "max_binance_limit_retries": 25, "open_wait_after_cancel_part": 2.0, "close_wait_after_cancel_part": 2.0, "delayed_single_leg_check_delay": 10.0, "open_wait_after_cancel_no_trade": 3.0, "close_wait_after_cancel_no_trade": 3.0, "delayed_single_leg_second_check_delay": 1.0}		2026-04-03 17:24:09.730466	0bc9c5f7-dc77-4f7d-bfbf-4b347a934b24	\N
\.


--
-- Data for Name: timing_config_templates; Type: TABLE DATA; Schema: public; Owner: postgres
--

COPY public.timing_config_templates (id, strategy_type, name, description, config_data, created_at, created_by, updated_at) FROM stdin;
1	forward_opening	11	11	{"bybit_timeout": 0.1, "debounce_delay": 0.5, "api_retry_delay": 0.5, "api_retry_times": 3, "binance_timeout": 5, "mt5_deal_sync_wait": 3, "order_check_interval": 0.2, "opening_trigger_count": 3, "spread_check_interval": 2, "status_polling_interval": 5, "api_spam_prevention_delay": 3, "max_binance_limit_retries": 25, "open_wait_after_cancel_part": 2, "close_wait_after_cancel_part": 2, "delayed_single_leg_check_delay": 10, "open_wait_after_cancel_no_trade": 3, "close_wait_after_cancel_no_trade": 3, "delayed_single_leg_second_check_delay": 1}	2026-04-03 16:38:42.373892	0bc9c5f7-dc77-4f7d-bfbf-4b347a934b24	2026-04-03 16:38:42.373892
2	forward_opening	11	11	{"bybit_timeout": 0.1, "debounce_delay": 0.5, "api_retry_delay": 0.5, "api_retry_times": 3, "binance_timeout": 5, "mt5_deal_sync_wait": 3, "order_check_interval": 0.2, "opening_trigger_count": 3, "spread_check_interval": 2, "status_polling_interval": 5, "api_spam_prevention_delay": 3, "max_binance_limit_retries": 25, "open_wait_after_cancel_part": 2, "close_wait_after_cancel_part": 2, "delayed_single_leg_check_delay": 10, "open_wait_after_cancel_no_trade": 3, "close_wait_after_cancel_no_trade": 3, "delayed_single_leg_second_check_delay": 1}	2026-04-03 16:39:48.799742	0bc9c5f7-dc77-4f7d-bfbf-4b347a934b24	2026-04-03 16:39:48.799742
3	forward_opening	111	111	{"bybit_timeout": 0.1, "debounce_delay": 0.5, "api_retry_delay": 0.5, "api_retry_times": 3, "binance_timeout": 5, "mt5_deal_sync_wait": 3, "order_check_interval": 0.2, "opening_trigger_count": 3, "spread_check_interval": 2, "status_polling_interval": 5, "api_spam_prevention_delay": 3, "max_binance_limit_retries": 25, "open_wait_after_cancel_part": 2, "close_wait_after_cancel_part": 2, "delayed_single_leg_check_delay": 10, "open_wait_after_cancel_no_trade": 3, "close_wait_after_cancel_no_trade": 3, "delayed_single_leg_second_check_delay": 1}	2026-04-03 16:48:18.028031	0bc9c5f7-dc77-4f7d-bfbf-4b347a934b24	2026-04-03 16:48:18.028031
4	forward_opening	111	11111	{"bybit_timeout": 0.1, "debounce_delay": 0.5, "api_retry_delay": 0.5, "api_retry_times": 3, "binance_timeout": 5, "mt5_deal_sync_wait": 3, "order_check_interval": 0.2, "opening_trigger_count": 3, "spread_check_interval": 2, "status_polling_interval": 5, "api_spam_prevention_delay": 3, "max_binance_limit_retries": 25, "open_wait_after_cancel_part": 2, "close_wait_after_cancel_part": 2, "delayed_single_leg_check_delay": 10, "open_wait_after_cancel_no_trade": 3, "close_wait_after_cancel_no_trade": 3, "delayed_single_leg_second_check_delay": 1}	2026-04-03 16:48:40.63507	0bc9c5f7-dc77-4f7d-bfbf-4b347a934b24	2026-04-03 16:48:40.63507
5	forward_opening	111	111111111	{"bybit_timeout": 0.1, "debounce_delay": 0.5, "api_retry_delay": 0.5, "api_retry_times": 3, "binance_timeout": 5, "mt5_deal_sync_wait": 3, "order_check_interval": 0.2, "opening_trigger_count": 3, "spread_check_interval": 2, "status_polling_interval": 5, "api_spam_prevention_delay": 3, "max_binance_limit_retries": 25, "open_wait_after_cancel_part": 2, "close_wait_after_cancel_part": 2, "delayed_single_leg_check_delay": 10, "open_wait_after_cancel_no_trade": 3, "close_wait_after_cancel_no_trade": 3, "delayed_single_leg_second_check_delay": 1}	2026-04-03 16:54:15.492411	0bc9c5f7-dc77-4f7d-bfbf-4b347a934b24	2026-04-03 16:54:15.492411
6	forward_opening	111	111111111	{"bybit_timeout": 0.1, "debounce_delay": 0.5, "api_retry_delay": 0.5, "api_retry_times": 3, "binance_timeout": 5, "mt5_deal_sync_wait": 3, "order_check_interval": 0.2, "opening_trigger_count": 3, "spread_check_interval": 2, "status_polling_interval": 5, "api_spam_prevention_delay": 3, "max_binance_limit_retries": 25, "open_wait_after_cancel_part": 2, "close_wait_after_cancel_part": 2, "delayed_single_leg_check_delay": 10, "open_wait_after_cancel_no_trade": 3, "close_wait_after_cancel_no_trade": 3, "delayed_single_leg_second_check_delay": 1}	2026-04-03 16:54:15.869386	0bc9c5f7-dc77-4f7d-bfbf-4b347a934b24	2026-04-03 16:54:15.869386
7	forward_opening	111	111111111	{"bybit_timeout": 0.1, "debounce_delay": 0.5, "api_retry_delay": 0.5, "api_retry_times": 3, "binance_timeout": 5, "mt5_deal_sync_wait": 3, "order_check_interval": 0.2, "opening_trigger_count": 3, "spread_check_interval": 2, "status_polling_interval": 5, "api_spam_prevention_delay": 3, "max_binance_limit_retries": 25, "open_wait_after_cancel_part": 2, "close_wait_after_cancel_part": 2, "delayed_single_leg_check_delay": 10, "open_wait_after_cancel_no_trade": 3, "close_wait_after_cancel_no_trade": 3, "delayed_single_leg_second_check_delay": 1}	2026-04-03 16:54:16.161287	0bc9c5f7-dc77-4f7d-bfbf-4b347a934b24	2026-04-03 16:54:16.161287
\.


--
-- Data for Name: trades; Type: TABLE DATA; Schema: public; Owner: postgres
--

COPY public.trades (trade_id, user_id, account_id, position_id, symbol, platform, side, trade_type, price, quantity, fee, realized_pnl, "timestamp", created_at) FROM stdin;
\.


--
-- Data for Name: user_notification_settings; Type: TABLE DATA; Schema: public; Owner: postgres
--

COPY public.user_notification_settings (setting_id, user_id, feishu_user_id, feishu_enabled, email, email_enabled, phone, sms_enabled, enable_trade_notifications, enable_risk_notifications, enable_system_notifications, created_at, updated_at) FROM stdin;
\.


--
-- Data for Name: user_roles; Type: TABLE DATA; Schema: public; Owner: postgres
--

COPY public.user_roles (id, user_id, role_id, assigned_at, assigned_by, expires_at) FROM stdin;
3b39b4a1-1bd3-4990-a2ee-35ec4f2b7b93	0bc9c5f7-dc77-4f7d-bfbf-4b347a934b24	63ad1a14-2623-4287-9dbf-dae8429c667f	2026-02-25 11:40:25.787715	0bc9c5f7-dc77-4f7d-bfbf-4b347a934b24	\N
77c553d0-a6d2-4263-8924-a7c720934a8a	66764cd6-d1c9-4468-a478-85b526a16927	d3e8bb4a-d6e2-49d5-80b9-ce47d1d2af92	2026-02-25 11:40:37.897044	0bc9c5f7-dc77-4f7d-bfbf-4b347a934b24	\N
db72076d-a27d-4ba8-9425-70003b17a393	debdebe2-076c-4601-a415-a8ad3ffd89e1	d3e8bb4a-d6e2-49d5-80b9-ce47d1d2af92	2026-04-02 20:25:16.34673	0bc9c5f7-dc77-4f7d-bfbf-4b347a934b24	\N
\.


--
-- Data for Name: users; Type: TABLE DATA; Schema: public; Owner: postgres
--

COPY public.users (user_id, username, password_hash, email, create_time, update_time, is_active, role, feishu_open_id, feishu_mobile, feishu_union_id) FROM stdin;
66764cd6-d1c9-4468-a478-85b526a16927	cq987	$2b$12$prGM7CVJrmCIVhsHfju27e3DIKXKHrspBr1SMKxhaZQxPd09XEiOO	1@51.com	2026-02-20 13:28:05.250344	2026-04-02 16:53:40.015572	t	交易员	ou_613cc2eabae277733bdee67edb3d8cc5	+8619906779799	on_6b14703ea5d68e82f990f07c58bae466
0bc9c5f7-dc77-4f7d-bfbf-4b347a934b24	admin	$2b$12$HfZYAQ66c9297bZ06JGGBOxxJxzjnYaZya0d4JqX6PTCJ8u48ii6W	admin@hustle.com	2026-02-20 10:06:23.357013	2026-03-19 20:44:23.677267	t	管理员	ou_613cc2eabae277733bdee67edb3d8cc5	+8613957717158	on_6b14703ea5d68e82f990f07c58bae466
debdebe2-076c-4601-a415-a8ad3ffd89e1	no456	$2b$12$kWzbVDHMn45LaLQiZ0/Qxep1gSUSeYJ84rtWae973REmOF4rbJ7tK	1@6.com	2026-02-20 13:28:41.870101	2026-04-02 16:49:31.183904	t	交易员	\N	\N	\N
\.


--
-- Data for Name: version_backups; Type: TABLE DATA; Schema: public; Owner: postgres
--

COPY public.version_backups (backup_id, backup_filename, "timestamp", description, status) FROM stdin;
\.


--
-- Name: mt5_clients_client_id_seq; Type: SEQUENCE SET; Schema: public; Owner: postgres
--

SELECT pg_catalog.setval('public.mt5_clients_client_id_seq', 7, true);


--
-- Name: platforms_platform_id_seq; Type: SEQUENCE SET; Schema: public; Owner: postgres
--

SELECT pg_catalog.setval('public.platforms_platform_id_seq', 1, false);


--
-- Name: proxy_pool_id_seq; Type: SEQUENCE SET; Schema: public; Owner: postgres
--

SELECT pg_catalog.setval('public.proxy_pool_id_seq', 1, false);


--
-- Name: strategies_id_seq; Type: SEQUENCE SET; Schema: public; Owner: postgres
--

SELECT pg_catalog.setval('public.strategies_id_seq', 1, false);


--
-- Name: strategy_timing_configs_id_seq; Type: SEQUENCE SET; Schema: public; Owner: postgres
--

SELECT pg_catalog.setval('public.strategy_timing_configs_id_seq', 4, true);


--
-- Name: timing_config_history_id_seq; Type: SEQUENCE SET; Schema: public; Owner: postgres
--

SELECT pg_catalog.setval('public.timing_config_history_id_seq', 2, true);


--
-- Name: timing_config_templates_id_seq; Type: SEQUENCE SET; Schema: public; Owner: postgres
--

SELECT pg_catalog.setval('public.timing_config_templates_id_seq', 10, true);


--
-- Name: account_snapshots account_snapshots_pkey; Type: CONSTRAINT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.account_snapshots
    ADD CONSTRAINT account_snapshots_pkey PRIMARY KEY (snapshot_id);


--
-- Name: accounts accounts_pkey; Type: CONSTRAINT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.accounts
    ADD CONSTRAINT accounts_pkey PRIMARY KEY (account_id);


--
-- Name: alembic_version alembic_version_pkc; Type: CONSTRAINT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.alembic_version
    ADD CONSTRAINT alembic_version_pkc PRIMARY KEY (version_num);


--
-- Name: arbitrage_tasks arbitrage_tasks_pkey; Type: CONSTRAINT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.arbitrage_tasks
    ADD CONSTRAINT arbitrage_tasks_pkey PRIMARY KEY (task_id);


--
-- Name: audio_files audio_files_file_name_key; Type: CONSTRAINT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.audio_files
    ADD CONSTRAINT audio_files_file_name_key UNIQUE (file_name);


--
-- Name: audio_files audio_files_pkey; Type: CONSTRAINT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.audio_files
    ADD CONSTRAINT audio_files_pkey PRIMARY KEY (file_id);


--
-- Name: market_data market_data_pkey; Type: CONSTRAINT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.market_data
    ADD CONSTRAINT market_data_pkey PRIMARY KEY (id);


--
-- Name: mt5_clients mt5_clients_pkey; Type: CONSTRAINT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.mt5_clients
    ADD CONSTRAINT mt5_clients_pkey PRIMARY KEY (client_id);


--
-- Name: mt5_instances mt5_instances_instance_name_key; Type: CONSTRAINT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.mt5_instances
    ADD CONSTRAINT mt5_instances_instance_name_key UNIQUE (instance_name);


--
-- Name: mt5_instances mt5_instances_pkey; Type: CONSTRAINT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.mt5_instances
    ADD CONSTRAINT mt5_instances_pkey PRIMARY KEY (instance_id);


--
-- Name: mt5_instances mt5_instances_service_port_key; Type: CONSTRAINT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.mt5_instances
    ADD CONSTRAINT mt5_instances_service_port_key UNIQUE (service_port);


--
-- Name: notification_configs notification_configs_pkey; Type: CONSTRAINT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.notification_configs
    ADD CONSTRAINT notification_configs_pkey PRIMARY KEY (config_id);


--
-- Name: notification_configs notification_configs_service_type_key; Type: CONSTRAINT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.notification_configs
    ADD CONSTRAINT notification_configs_service_type_key UNIQUE (service_type);


--
-- Name: notification_logs notification_logs_pkey; Type: CONSTRAINT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.notification_logs
    ADD CONSTRAINT notification_logs_pkey PRIMARY KEY (log_id);


--
-- Name: notification_templates notification_templates_pkey; Type: CONSTRAINT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.notification_templates
    ADD CONSTRAINT notification_templates_pkey PRIMARY KEY (template_id);


--
-- Name: notification_templates notification_templates_template_key_key; Type: CONSTRAINT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.notification_templates
    ADD CONSTRAINT notification_templates_template_key_key UNIQUE (template_key);


--
-- Name: notifications notifications_pkey; Type: CONSTRAINT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.notifications
    ADD CONSTRAINT notifications_pkey PRIMARY KEY (notification_id);


--
-- Name: order_records order_records_pkey; Type: CONSTRAINT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.order_records
    ADD CONSTRAINT order_records_pkey PRIMARY KEY (order_id);


--
-- Name: permissions permissions_permission_code_key; Type: CONSTRAINT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.permissions
    ADD CONSTRAINT permissions_permission_code_key UNIQUE (permission_code);


--
-- Name: permissions permissions_pkey; Type: CONSTRAINT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.permissions
    ADD CONSTRAINT permissions_pkey PRIMARY KEY (permission_id);


--
-- Name: platforms platforms_pkey; Type: CONSTRAINT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.platforms
    ADD CONSTRAINT platforms_pkey PRIMARY KEY (platform_id);


--
-- Name: positions positions_pkey; Type: CONSTRAINT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.positions
    ADD CONSTRAINT positions_pkey PRIMARY KEY (position_id);


--
-- Name: proxy_pool proxy_pool_pkey; Type: CONSTRAINT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.proxy_pool
    ADD CONSTRAINT proxy_pool_pkey PRIMARY KEY (id);


--
-- Name: risk_alerts risk_alerts_pkey; Type: CONSTRAINT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.risk_alerts
    ADD CONSTRAINT risk_alerts_pkey PRIMARY KEY (alert_id);


--
-- Name: risk_settings risk_settings_pkey; Type: CONSTRAINT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.risk_settings
    ADD CONSTRAINT risk_settings_pkey PRIMARY KEY (settings_id);


--
-- Name: risk_settings risk_settings_user_id_key; Type: CONSTRAINT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.risk_settings
    ADD CONSTRAINT risk_settings_user_id_key UNIQUE (user_id);


--
-- Name: role_permissions role_permissions_pkey; Type: CONSTRAINT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.role_permissions
    ADD CONSTRAINT role_permissions_pkey PRIMARY KEY (id);


--
-- Name: role_permissions role_permissions_role_id_permission_id_key; Type: CONSTRAINT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.role_permissions
    ADD CONSTRAINT role_permissions_role_id_permission_id_key UNIQUE (role_id, permission_id);


--
-- Name: roles roles_pkey; Type: CONSTRAINT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.roles
    ADD CONSTRAINT roles_pkey PRIMARY KEY (role_id);


--
-- Name: roles roles_role_code_key; Type: CONSTRAINT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.roles
    ADD CONSTRAINT roles_role_code_key UNIQUE (role_code);


--
-- Name: roles roles_role_name_key; Type: CONSTRAINT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.roles
    ADD CONSTRAINT roles_role_name_key UNIQUE (role_name);


--
-- Name: security_component_logs security_component_logs_pkey; Type: CONSTRAINT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.security_component_logs
    ADD CONSTRAINT security_component_logs_pkey PRIMARY KEY (log_id);


--
-- Name: security_components security_components_component_code_key; Type: CONSTRAINT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.security_components
    ADD CONSTRAINT security_components_component_code_key UNIQUE (component_code);


--
-- Name: security_components security_components_pkey; Type: CONSTRAINT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.security_components
    ADD CONSTRAINT security_components_pkey PRIMARY KEY (component_id);


--
-- Name: spread_records spread_records_pkey; Type: CONSTRAINT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.spread_records
    ADD CONSTRAINT spread_records_pkey PRIMARY KEY (id);


--
-- Name: ssl_certificate_logs ssl_certificate_logs_pkey; Type: CONSTRAINT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.ssl_certificate_logs
    ADD CONSTRAINT ssl_certificate_logs_pkey PRIMARY KEY (log_id);


--
-- Name: ssl_certificates ssl_certificates_domain_name_cert_type_key; Type: CONSTRAINT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.ssl_certificates
    ADD CONSTRAINT ssl_certificates_domain_name_cert_type_key UNIQUE (domain_name, cert_type);


--
-- Name: ssl_certificates ssl_certificates_pkey; Type: CONSTRAINT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.ssl_certificates
    ADD CONSTRAINT ssl_certificates_pkey PRIMARY KEY (cert_id);


--
-- Name: strategies strategies_pkey; Type: CONSTRAINT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.strategies
    ADD CONSTRAINT strategies_pkey PRIMARY KEY (id);


--
-- Name: strategy_configs strategy_configs_pkey; Type: CONSTRAINT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.strategy_configs
    ADD CONSTRAINT strategy_configs_pkey PRIMARY KEY (config_id);


--
-- Name: strategy_performance strategy_performance_pkey; Type: CONSTRAINT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.strategy_performance
    ADD CONSTRAINT strategy_performance_pkey PRIMARY KEY (performance_id);


--
-- Name: strategy_timing_configs strategy_timing_configs_pkey; Type: CONSTRAINT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.strategy_timing_configs
    ADD CONSTRAINT strategy_timing_configs_pkey PRIMARY KEY (id);


--
-- Name: system_alerts system_alerts_pkey; Type: CONSTRAINT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.system_alerts
    ADD CONSTRAINT system_alerts_pkey PRIMARY KEY (alert_id);


--
-- Name: system_logs system_logs_pkey; Type: CONSTRAINT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.system_logs
    ADD CONSTRAINT system_logs_pkey PRIMARY KEY (log_id);


--
-- Name: timing_config_history timing_config_history_pkey; Type: CONSTRAINT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.timing_config_history
    ADD CONSTRAINT timing_config_history_pkey PRIMARY KEY (id);


--
-- Name: timing_config_templates timing_config_templates_pkey; Type: CONSTRAINT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.timing_config_templates
    ADD CONSTRAINT timing_config_templates_pkey PRIMARY KEY (id);


--
-- Name: trades trades_pkey; Type: CONSTRAINT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.trades
    ADD CONSTRAINT trades_pkey PRIMARY KEY (trade_id);


--
-- Name: user_notification_settings user_notification_settings_pkey; Type: CONSTRAINT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.user_notification_settings
    ADD CONSTRAINT user_notification_settings_pkey PRIMARY KEY (setting_id);


--
-- Name: user_notification_settings user_notification_settings_user_id_key; Type: CONSTRAINT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.user_notification_settings
    ADD CONSTRAINT user_notification_settings_user_id_key UNIQUE (user_id);


--
-- Name: user_roles user_roles_pkey; Type: CONSTRAINT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.user_roles
    ADD CONSTRAINT user_roles_pkey PRIMARY KEY (id);


--
-- Name: user_roles user_roles_user_id_role_id_key; Type: CONSTRAINT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.user_roles
    ADD CONSTRAINT user_roles_user_id_role_id_key UNIQUE (user_id, role_id);


--
-- Name: users users_pkey; Type: CONSTRAINT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.users
    ADD CONSTRAINT users_pkey PRIMARY KEY (user_id);


--
-- Name: version_backups version_backups_pkey; Type: CONSTRAINT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.version_backups
    ADD CONSTRAINT version_backups_pkey PRIMARY KEY (backup_id);


--
-- Name: idx_account_snapshots_account_time; Type: INDEX; Schema: public; Owner: postgres
--

CREATE INDEX idx_account_snapshots_account_time ON public.account_snapshots USING btree (account_id, "timestamp");


--
-- Name: idx_market_data_symbol_platform_time; Type: INDEX; Schema: public; Owner: postgres
--

CREATE INDEX idx_market_data_symbol_platform_time ON public.market_data USING btree (symbol, platform, "timestamp");


--
-- Name: idx_mt5_clients_system_service; Type: INDEX; Schema: public; Owner: postgres
--

CREATE INDEX idx_mt5_clients_system_service ON public.mt5_clients USING btree (is_system_service);


--
-- Name: idx_mt5_instances_active; Type: INDEX; Schema: public; Owner: postgres
--

CREATE INDEX idx_mt5_instances_active ON public.mt5_instances USING btree (is_active);


--
-- Name: idx_mt5_instances_client_id; Type: INDEX; Schema: public; Owner: postgres
--

CREATE INDEX idx_mt5_instances_client_id ON public.mt5_instances USING btree (client_id);


--
-- Name: idx_mt5_instances_client_type; Type: INDEX; Schema: public; Owner: postgres
--

CREATE UNIQUE INDEX idx_mt5_instances_client_type ON public.mt5_instances USING btree (client_id, instance_type) WHERE (client_id IS NOT NULL);


--
-- Name: idx_mt5_instances_server_ip; Type: INDEX; Schema: public; Owner: postgres
--

CREATE INDEX idx_mt5_instances_server_ip ON public.mt5_instances USING btree (server_ip);


--
-- Name: idx_mt5_instances_status; Type: INDEX; Schema: public; Owner: postgres
--

CREATE INDEX idx_mt5_instances_status ON public.mt5_instances USING btree (status);


--
-- Name: idx_mt5_instances_type; Type: INDEX; Schema: public; Owner: postgres
--

CREATE INDEX idx_mt5_instances_type ON public.mt5_instances USING btree (instance_type);


--
-- Name: idx_notification_logs_created; Type: INDEX; Schema: public; Owner: postgres
--

CREATE INDEX idx_notification_logs_created ON public.notification_logs USING btree (created_at DESC);


--
-- Name: idx_notification_logs_status; Type: INDEX; Schema: public; Owner: postgres
--

CREATE INDEX idx_notification_logs_status ON public.notification_logs USING btree (status);


--
-- Name: idx_notification_logs_user; Type: INDEX; Schema: public; Owner: postgres
--

CREATE INDEX idx_notification_logs_user ON public.notification_logs USING btree (user_id);


--
-- Name: idx_notification_templates_active; Type: INDEX; Schema: public; Owner: postgres
--

CREATE INDEX idx_notification_templates_active ON public.notification_templates USING btree (is_active);


--
-- Name: idx_notification_templates_category; Type: INDEX; Schema: public; Owner: postgres
--

CREATE INDEX idx_notification_templates_category ON public.notification_templates USING btree (category);


--
-- Name: idx_notifications_created_at; Type: INDEX; Schema: public; Owner: postgres
--

CREATE INDEX idx_notifications_created_at ON public.notifications USING btree (created_at);


--
-- Name: idx_notifications_user_id; Type: INDEX; Schema: public; Owner: postgres
--

CREATE INDEX idx_notifications_user_id ON public.notifications USING btree (user_id);


--
-- Name: idx_notifications_user_read; Type: INDEX; Schema: public; Owner: postgres
--

CREATE INDEX idx_notifications_user_read ON public.notifications USING btree (user_id, is_read);


--
-- Name: idx_permissions_code; Type: INDEX; Schema: public; Owner: postgres
--

CREATE INDEX idx_permissions_code ON public.permissions USING btree (permission_code);


--
-- Name: idx_permissions_parent; Type: INDEX; Schema: public; Owner: postgres
--

CREATE INDEX idx_permissions_parent ON public.permissions USING btree (parent_id);


--
-- Name: idx_permissions_type; Type: INDEX; Schema: public; Owner: postgres
--

CREATE INDEX idx_permissions_type ON public.permissions USING btree (resource_type);


--
-- Name: idx_positions_user_open; Type: INDEX; Schema: public; Owner: postgres
--

CREATE INDEX idx_positions_user_open ON public.positions USING btree (user_id, is_open);


--
-- Name: idx_proxy_pool_expire; Type: INDEX; Schema: public; Owner: postgres
--

CREATE INDEX idx_proxy_pool_expire ON public.proxy_pool USING btree (expire_time);


--
-- Name: idx_proxy_pool_health; Type: INDEX; Schema: public; Owner: postgres
--

CREATE INDEX idx_proxy_pool_health ON public.proxy_pool USING btree (health_score);


--
-- Name: idx_proxy_pool_provider; Type: INDEX; Schema: public; Owner: postgres
--

CREATE INDEX idx_proxy_pool_provider ON public.proxy_pool USING btree (provider);


--
-- Name: idx_proxy_pool_status; Type: INDEX; Schema: public; Owner: postgres
--

CREATE INDEX idx_proxy_pool_status ON public.proxy_pool USING btree (status);


--
-- Name: idx_risk_settings_user_id; Type: INDEX; Schema: public; Owner: postgres
--

CREATE INDEX idx_risk_settings_user_id ON public.risk_settings USING btree (user_id);


--
-- Name: idx_role_permissions_permission; Type: INDEX; Schema: public; Owner: postgres
--

CREATE INDEX idx_role_permissions_permission ON public.role_permissions USING btree (permission_id);


--
-- Name: idx_role_permissions_role; Type: INDEX; Schema: public; Owner: postgres
--

CREATE INDEX idx_role_permissions_role ON public.role_permissions USING btree (role_id);


--
-- Name: idx_roles_active; Type: INDEX; Schema: public; Owner: postgres
--

CREATE INDEX idx_roles_active ON public.roles USING btree (is_active);


--
-- Name: idx_roles_code; Type: INDEX; Schema: public; Owner: postgres
--

CREATE INDEX idx_roles_code ON public.roles USING btree (role_code);


--
-- Name: idx_security_components_code; Type: INDEX; Schema: public; Owner: postgres
--

CREATE INDEX idx_security_components_code ON public.security_components USING btree (component_code);


--
-- Name: idx_security_components_enabled; Type: INDEX; Schema: public; Owner: postgres
--

CREATE INDEX idx_security_components_enabled ON public.security_components USING btree (is_enabled);


--
-- Name: idx_security_components_type; Type: INDEX; Schema: public; Owner: postgres
--

CREATE INDEX idx_security_components_type ON public.security_components USING btree (component_type);


--
-- Name: idx_security_logs_action; Type: INDEX; Schema: public; Owner: postgres
--

CREATE INDEX idx_security_logs_action ON public.security_component_logs USING btree (action);


--
-- Name: idx_security_logs_component; Type: INDEX; Schema: public; Owner: postgres
--

CREATE INDEX idx_security_logs_component ON public.security_component_logs USING btree (component_id);


--
-- Name: idx_security_logs_time; Type: INDEX; Schema: public; Owner: postgres
--

CREATE INDEX idx_security_logs_time ON public.security_component_logs USING btree (performed_at DESC);


--
-- Name: idx_spread_records_time; Type: INDEX; Schema: public; Owner: postgres
--

CREATE INDEX idx_spread_records_time ON public.spread_records USING btree ("timestamp");


--
-- Name: idx_ssl_certs_domain; Type: INDEX; Schema: public; Owner: postgres
--

CREATE INDEX idx_ssl_certs_domain ON public.ssl_certificates USING btree (domain_name);


--
-- Name: idx_ssl_certs_expires; Type: INDEX; Schema: public; Owner: postgres
--

CREATE INDEX idx_ssl_certs_expires ON public.ssl_certificates USING btree (expires_at);


--
-- Name: idx_ssl_certs_status; Type: INDEX; Schema: public; Owner: postgres
--

CREATE INDEX idx_ssl_certs_status ON public.ssl_certificates USING btree (status);


--
-- Name: idx_ssl_logs_action; Type: INDEX; Schema: public; Owner: postgres
--

CREATE INDEX idx_ssl_logs_action ON public.ssl_certificate_logs USING btree (action);


--
-- Name: idx_ssl_logs_cert; Type: INDEX; Schema: public; Owner: postgres
--

CREATE INDEX idx_ssl_logs_cert ON public.ssl_certificate_logs USING btree (cert_id);


--
-- Name: idx_ssl_logs_time; Type: INDEX; Schema: public; Owner: postgres
--

CREATE INDEX idx_ssl_logs_time ON public.ssl_certificate_logs USING btree (performed_at DESC);


--
-- Name: idx_strategy_performance_strategy_date; Type: INDEX; Schema: public; Owner: postgres
--

CREATE INDEX idx_strategy_performance_strategy_date ON public.strategy_performance USING btree (strategy_id, date);


--
-- Name: idx_system_alerts_user_read; Type: INDEX; Schema: public; Owner: postgres
--

CREATE INDEX idx_system_alerts_user_read ON public.system_alerts USING btree (user_id, is_read);


--
-- Name: idx_system_alerts_user_time; Type: INDEX; Schema: public; Owner: postgres
--

CREATE INDEX idx_system_alerts_user_time ON public.system_alerts USING btree (user_id, "timestamp");


--
-- Name: idx_system_logs_category_time; Type: INDEX; Schema: public; Owner: postgres
--

CREATE INDEX idx_system_logs_category_time ON public.system_logs USING btree (category, "timestamp");


--
-- Name: idx_system_logs_level_time; Type: INDEX; Schema: public; Owner: postgres
--

CREATE INDEX idx_system_logs_level_time ON public.system_logs USING btree (level, "timestamp");


--
-- Name: idx_system_logs_timestamp; Type: INDEX; Schema: public; Owner: postgres
--

CREATE INDEX idx_system_logs_timestamp ON public.system_logs USING btree ("timestamp");


--
-- Name: idx_system_logs_user_id; Type: INDEX; Schema: public; Owner: postgres
--

CREATE INDEX idx_system_logs_user_id ON public.system_logs USING btree (user_id);


--
-- Name: idx_trades_account_time; Type: INDEX; Schema: public; Owner: postgres
--

CREATE INDEX idx_trades_account_time ON public.trades USING btree (account_id, "timestamp");


--
-- Name: idx_trades_position; Type: INDEX; Schema: public; Owner: postgres
--

CREATE INDEX idx_trades_position ON public.trades USING btree (position_id);


--
-- Name: idx_trades_user_time; Type: INDEX; Schema: public; Owner: postgres
--

CREATE INDEX idx_trades_user_time ON public.trades USING btree (user_id, "timestamp");


--
-- Name: idx_user_notification_settings_user; Type: INDEX; Schema: public; Owner: postgres
--

CREATE INDEX idx_user_notification_settings_user ON public.user_notification_settings USING btree (user_id);


--
-- Name: idx_user_roles_role; Type: INDEX; Schema: public; Owner: postgres
--

CREATE INDEX idx_user_roles_role ON public.user_roles USING btree (role_id);


--
-- Name: idx_user_roles_user; Type: INDEX; Schema: public; Owner: postgres
--

CREATE INDEX idx_user_roles_user ON public.user_roles USING btree (user_id);


--
-- Name: idx_users_feishu_open_id; Type: INDEX; Schema: public; Owner: postgres
--

CREATE INDEX idx_users_feishu_open_id ON public.users USING btree (feishu_open_id);


--
-- Name: ix_accounts_user_id; Type: INDEX; Schema: public; Owner: postgres
--

CREATE INDEX ix_accounts_user_id ON public.accounts USING btree (user_id);


--
-- Name: ix_arbitrage_tasks_user_id; Type: INDEX; Schema: public; Owner: postgres
--

CREATE INDEX ix_arbitrage_tasks_user_id ON public.arbitrage_tasks USING btree (user_id);


--
-- Name: ix_market_data_timestamp; Type: INDEX; Schema: public; Owner: postgres
--

CREATE INDEX ix_market_data_timestamp ON public.market_data USING btree ("timestamp");


--
-- Name: ix_order_records_account_id; Type: INDEX; Schema: public; Owner: postgres
--

CREATE INDEX ix_order_records_account_id ON public.order_records USING btree (account_id);


--
-- Name: ix_positions_account_id; Type: INDEX; Schema: public; Owner: postgres
--

CREATE INDEX ix_positions_account_id ON public.positions USING btree (account_id);


--
-- Name: ix_positions_user_id; Type: INDEX; Schema: public; Owner: postgres
--

CREATE INDEX ix_positions_user_id ON public.positions USING btree (user_id);


--
-- Name: ix_risk_alerts_user_id; Type: INDEX; Schema: public; Owner: postgres
--

CREATE INDEX ix_risk_alerts_user_id ON public.risk_alerts USING btree (user_id);


--
-- Name: ix_spread_records_timestamp; Type: INDEX; Schema: public; Owner: postgres
--

CREATE INDEX ix_spread_records_timestamp ON public.spread_records USING btree ("timestamp");


--
-- Name: ix_strategies_user_id; Type: INDEX; Schema: public; Owner: postgres
--

CREATE INDEX ix_strategies_user_id ON public.strategies USING btree (user_id);


--
-- Name: ix_strategy_configs_user_id; Type: INDEX; Schema: public; Owner: postgres
--

CREATE INDEX ix_strategy_configs_user_id ON public.strategy_configs USING btree (user_id);


--
-- Name: ix_users_email; Type: INDEX; Schema: public; Owner: postgres
--

CREATE UNIQUE INDEX ix_users_email ON public.users USING btree (email);


--
-- Name: ix_users_username; Type: INDEX; Schema: public; Owner: postgres
--

CREATE UNIQUE INDEX ix_users_username ON public.users USING btree (username);


--
-- Name: permissions update_permissions_updated_at; Type: TRIGGER; Schema: public; Owner: postgres
--

CREATE TRIGGER update_permissions_updated_at BEFORE UPDATE ON public.permissions FOR EACH ROW EXECUTE FUNCTION public.update_updated_at_column();


--
-- Name: roles update_roles_updated_at; Type: TRIGGER; Schema: public; Owner: postgres
--

CREATE TRIGGER update_roles_updated_at BEFORE UPDATE ON public.roles FOR EACH ROW EXECUTE FUNCTION public.update_updated_at_column();


--
-- Name: security_components update_security_components_updated_at; Type: TRIGGER; Schema: public; Owner: postgres
--

CREATE TRIGGER update_security_components_updated_at BEFORE UPDATE ON public.security_components FOR EACH ROW EXECUTE FUNCTION public.update_updated_at_column();


--
-- Name: ssl_certificates update_ssl_certificates_updated_at; Type: TRIGGER; Schema: public; Owner: postgres
--

CREATE TRIGGER update_ssl_certificates_updated_at BEFORE UPDATE ON public.ssl_certificates FOR EACH ROW EXECUTE FUNCTION public.update_updated_at_column();


--
-- Name: account_snapshots account_snapshots_account_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.account_snapshots
    ADD CONSTRAINT account_snapshots_account_id_fkey FOREIGN KEY (account_id) REFERENCES public.accounts(account_id);


--
-- Name: accounts accounts_platform_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.accounts
    ADD CONSTRAINT accounts_platform_id_fkey FOREIGN KEY (platform_id) REFERENCES public.platforms(platform_id);


--
-- Name: accounts accounts_user_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.accounts
    ADD CONSTRAINT accounts_user_id_fkey FOREIGN KEY (user_id) REFERENCES public.users(user_id);


--
-- Name: arbitrage_tasks arbitrage_tasks_user_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.arbitrage_tasks
    ADD CONSTRAINT arbitrage_tasks_user_id_fkey FOREIGN KEY (user_id) REFERENCES public.users(user_id);


--
-- Name: strategy_timing_configs fk_timing_configs_created_by; Type: FK CONSTRAINT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.strategy_timing_configs
    ADD CONSTRAINT fk_timing_configs_created_by FOREIGN KEY (created_by) REFERENCES public.users(user_id) ON DELETE SET NULL;


--
-- Name: mt5_clients mt5_clients_account_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.mt5_clients
    ADD CONSTRAINT mt5_clients_account_id_fkey FOREIGN KEY (account_id) REFERENCES public.accounts(account_id) ON DELETE CASCADE;


--
-- Name: mt5_instances mt5_instances_client_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.mt5_instances
    ADD CONSTRAINT mt5_instances_client_id_fkey FOREIGN KEY (client_id) REFERENCES public.mt5_clients(client_id) ON DELETE CASCADE;


--
-- Name: notification_logs notification_logs_user_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.notification_logs
    ADD CONSTRAINT notification_logs_user_id_fkey FOREIGN KEY (user_id) REFERENCES public.users(user_id);


--
-- Name: notifications notifications_user_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.notifications
    ADD CONSTRAINT notifications_user_id_fkey FOREIGN KEY (user_id) REFERENCES public.users(user_id) ON DELETE CASCADE;


--
-- Name: order_records order_records_account_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.order_records
    ADD CONSTRAINT order_records_account_id_fkey FOREIGN KEY (account_id) REFERENCES public.accounts(account_id);


--
-- Name: permissions permissions_parent_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.permissions
    ADD CONSTRAINT permissions_parent_id_fkey FOREIGN KEY (parent_id) REFERENCES public.permissions(permission_id);


--
-- Name: positions positions_account_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.positions
    ADD CONSTRAINT positions_account_id_fkey FOREIGN KEY (account_id) REFERENCES public.accounts(account_id);


--
-- Name: positions positions_user_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.positions
    ADD CONSTRAINT positions_user_id_fkey FOREIGN KEY (user_id) REFERENCES public.users(user_id);


--
-- Name: risk_alerts risk_alerts_user_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.risk_alerts
    ADD CONSTRAINT risk_alerts_user_id_fkey FOREIGN KEY (user_id) REFERENCES public.users(user_id);


--
-- Name: risk_settings risk_settings_user_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.risk_settings
    ADD CONSTRAINT risk_settings_user_id_fkey FOREIGN KEY (user_id) REFERENCES public.users(user_id) ON DELETE CASCADE;


--
-- Name: role_permissions role_permissions_granted_by_fkey; Type: FK CONSTRAINT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.role_permissions
    ADD CONSTRAINT role_permissions_granted_by_fkey FOREIGN KEY (granted_by) REFERENCES public.users(user_id);


--
-- Name: role_permissions role_permissions_permission_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.role_permissions
    ADD CONSTRAINT role_permissions_permission_id_fkey FOREIGN KEY (permission_id) REFERENCES public.permissions(permission_id) ON DELETE CASCADE;


--
-- Name: role_permissions role_permissions_role_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.role_permissions
    ADD CONSTRAINT role_permissions_role_id_fkey FOREIGN KEY (role_id) REFERENCES public.roles(role_id) ON DELETE CASCADE;


--
-- Name: roles roles_created_by_fkey; Type: FK CONSTRAINT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.roles
    ADD CONSTRAINT roles_created_by_fkey FOREIGN KEY (created_by) REFERENCES public.users(user_id);


--
-- Name: roles roles_updated_by_fkey; Type: FK CONSTRAINT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.roles
    ADD CONSTRAINT roles_updated_by_fkey FOREIGN KEY (updated_by) REFERENCES public.users(user_id);


--
-- Name: security_component_logs security_component_logs_component_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.security_component_logs
    ADD CONSTRAINT security_component_logs_component_id_fkey FOREIGN KEY (component_id) REFERENCES public.security_components(component_id) ON DELETE CASCADE;


--
-- Name: security_component_logs security_component_logs_performed_by_fkey; Type: FK CONSTRAINT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.security_component_logs
    ADD CONSTRAINT security_component_logs_performed_by_fkey FOREIGN KEY (performed_by) REFERENCES public.users(user_id);


--
-- Name: security_components security_components_created_by_fkey; Type: FK CONSTRAINT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.security_components
    ADD CONSTRAINT security_components_created_by_fkey FOREIGN KEY (created_by) REFERENCES public.users(user_id);


--
-- Name: security_components security_components_updated_by_fkey; Type: FK CONSTRAINT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.security_components
    ADD CONSTRAINT security_components_updated_by_fkey FOREIGN KEY (updated_by) REFERENCES public.users(user_id);


--
-- Name: ssl_certificate_logs ssl_certificate_logs_cert_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.ssl_certificate_logs
    ADD CONSTRAINT ssl_certificate_logs_cert_id_fkey FOREIGN KEY (cert_id) REFERENCES public.ssl_certificates(cert_id) ON DELETE CASCADE;


--
-- Name: ssl_certificate_logs ssl_certificate_logs_performed_by_fkey; Type: FK CONSTRAINT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.ssl_certificate_logs
    ADD CONSTRAINT ssl_certificate_logs_performed_by_fkey FOREIGN KEY (performed_by) REFERENCES public.users(user_id);


--
-- Name: ssl_certificates ssl_certificates_uploaded_by_fkey; Type: FK CONSTRAINT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.ssl_certificates
    ADD CONSTRAINT ssl_certificates_uploaded_by_fkey FOREIGN KEY (uploaded_by) REFERENCES public.users(user_id);


--
-- Name: strategies strategies_user_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.strategies
    ADD CONSTRAINT strategies_user_id_fkey FOREIGN KEY (user_id) REFERENCES public.users(user_id);


--
-- Name: strategy_configs strategy_configs_user_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.strategy_configs
    ADD CONSTRAINT strategy_configs_user_id_fkey FOREIGN KEY (user_id) REFERENCES public.users(user_id);


--
-- Name: strategy_performance strategy_performance_strategy_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.strategy_performance
    ADD CONSTRAINT strategy_performance_strategy_id_fkey FOREIGN KEY (strategy_id) REFERENCES public.strategies(id);


--
-- Name: strategy_timing_configs strategy_timing_configs_locked_by_fkey; Type: FK CONSTRAINT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.strategy_timing_configs
    ADD CONSTRAINT strategy_timing_configs_locked_by_fkey FOREIGN KEY (locked_by) REFERENCES public.users(user_id) ON DELETE SET NULL;


--
-- Name: system_alerts system_alerts_user_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.system_alerts
    ADD CONSTRAINT system_alerts_user_id_fkey FOREIGN KEY (user_id) REFERENCES public.users(user_id);


--
-- Name: system_logs system_logs_user_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.system_logs
    ADD CONSTRAINT system_logs_user_id_fkey FOREIGN KEY (user_id) REFERENCES public.users(user_id) ON DELETE SET NULL;


--
-- Name: timing_config_history timing_config_history_config_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.timing_config_history
    ADD CONSTRAINT timing_config_history_config_id_fkey FOREIGN KEY (config_id) REFERENCES public.strategy_timing_configs(id) ON DELETE CASCADE;


--
-- Name: timing_config_history timing_config_history_created_by_fkey; Type: FK CONSTRAINT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.timing_config_history
    ADD CONSTRAINT timing_config_history_created_by_fkey FOREIGN KEY (created_by) REFERENCES public.users(user_id) ON DELETE SET NULL;


--
-- Name: timing_config_templates timing_config_templates_created_by_fkey; Type: FK CONSTRAINT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.timing_config_templates
    ADD CONSTRAINT timing_config_templates_created_by_fkey FOREIGN KEY (created_by) REFERENCES public.users(user_id) ON DELETE SET NULL;


--
-- Name: trades trades_account_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.trades
    ADD CONSTRAINT trades_account_id_fkey FOREIGN KEY (account_id) REFERENCES public.accounts(account_id);


--
-- Name: trades trades_position_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.trades
    ADD CONSTRAINT trades_position_id_fkey FOREIGN KEY (position_id) REFERENCES public.positions(position_id);


--
-- Name: trades trades_user_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.trades
    ADD CONSTRAINT trades_user_id_fkey FOREIGN KEY (user_id) REFERENCES public.users(user_id);


--
-- Name: user_notification_settings user_notification_settings_user_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.user_notification_settings
    ADD CONSTRAINT user_notification_settings_user_id_fkey FOREIGN KEY (user_id) REFERENCES public.users(user_id);


--
-- Name: user_roles user_roles_assigned_by_fkey; Type: FK CONSTRAINT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.user_roles
    ADD CONSTRAINT user_roles_assigned_by_fkey FOREIGN KEY (assigned_by) REFERENCES public.users(user_id);


--
-- Name: user_roles user_roles_role_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.user_roles
    ADD CONSTRAINT user_roles_role_id_fkey FOREIGN KEY (role_id) REFERENCES public.roles(role_id) ON DELETE CASCADE;


--
-- Name: user_roles user_roles_user_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.user_roles
    ADD CONSTRAINT user_roles_user_id_fkey FOREIGN KEY (user_id) REFERENCES public.users(user_id) ON DELETE CASCADE;


--
-- Name: SCHEMA public; Type: ACL; Schema: -; Owner: postgres
--

REVOKE USAGE ON SCHEMA public FROM PUBLIC;


--
-- PostgreSQL database dump complete
--

\unrestrict Dx2D55naMQY4O28aZW3u9zX4PqV75TR039glIQoOVECHlRNsKEW6SIDyKblbczU

