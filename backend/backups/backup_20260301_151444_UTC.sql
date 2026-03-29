--
-- PostgreSQL database dump
--

\restrict 3toF3YMs01ArngYvhSr8ZzeRtYIUEeABZkH2MgfXYl2aTDasm22hQGtoncoWqmU

-- Dumped from database version 16.12
-- Dumped by pg_dump version 16.12

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
-- Name: adminpack; Type: EXTENSION; Schema: -; Owner: -
--

CREATE EXTENSION IF NOT EXISTS adminpack WITH SCHEMA pg_catalog;


--
-- Name: EXTENSION adminpack; Type: COMMENT; Schema: -; Owner: 
--

COMMENT ON EXTENSION adminpack IS 'administrative functions for PostgreSQL';


--
-- Name: pgagent; Type: EXTENSION; Schema: -; Owner: -
--

CREATE EXTENSION IF NOT EXISTS pgagent WITH SCHEMA pgagent;


--
-- Name: EXTENSION pgagent; Type: COMMENT; Schema: -; Owner: 
--

COMMENT ON EXTENSION pgagent IS 'A PostgreSQL job scheduler';


--
-- Name: pgcrypto; Type: EXTENSION; Schema: -; Owner: -
--

CREATE EXTENSION IF NOT EXISTS pgcrypto WITH SCHEMA public;


--
-- Name: EXTENSION pgcrypto; Type: COMMENT; Schema: -; Owner: 
--

COMMENT ON EXTENSION pgcrypto IS 'cryptographic functions';


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
    account_id uuid NOT NULL,
    user_id uuid NOT NULL,
    platform_id smallint NOT NULL,
    account_name character varying(50) NOT NULL,
    api_key character varying(256) NOT NULL,
    api_secret character varying(256) NOT NULL,
    passphrase character varying(100),
    mt5_id character varying(100),
    mt5_server character varying(100),
    mt5_primary_pwd character varying(256),
    is_mt5_account boolean NOT NULL,
    is_default boolean NOT NULL,
    is_active boolean NOT NULL,
    create_time timestamp without time zone NOT NULL,
    update_time timestamp without time zone NOT NULL,
    mt5_password character varying(500),
    last_sync_time timestamp without time zone,
    leverage integer
);


ALTER TABLE public.accounts OWNER TO postgres;

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
    closing_m_coin double precision NOT NULL
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
    role character varying(50) DEFAULT '交易员'::character varying NOT NULL
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
-- Name: platforms platform_id; Type: DEFAULT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.platforms ALTER COLUMN platform_id SET DEFAULT nextval('public.platforms_platform_id_seq'::regclass);


--
-- Name: strategies id; Type: DEFAULT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.strategies ALTER COLUMN id SET DEFAULT nextval('public.strategies_id_seq'::regclass);


--
-- Data for Name: pga_jobagent; Type: TABLE DATA; Schema: pgagent; Owner: postgres
--

COPY pgagent.pga_jobagent (jagpid, jaglogintime, jagstation) FROM stdin;
\.


--
-- Data for Name: pga_jobclass; Type: TABLE DATA; Schema: pgagent; Owner: postgres
--

COPY pgagent.pga_jobclass (jclid, jclname) FROM stdin;
\.


--
-- Data for Name: pga_job; Type: TABLE DATA; Schema: pgagent; Owner: postgres
--

COPY pgagent.pga_job (jobid, jobjclid, jobname, jobdesc, jobhostagent, jobenabled, jobcreated, jobchanged, jobagentid, jobnextrun, joblastrun) FROM stdin;
\.


--
-- Data for Name: pga_schedule; Type: TABLE DATA; Schema: pgagent; Owner: postgres
--

COPY pgagent.pga_schedule (jscid, jscjobid, jscname, jscdesc, jscenabled, jscstart, jscend, jscminutes, jschours, jscweekdays, jscmonthdays, jscmonths) FROM stdin;
\.


--
-- Data for Name: pga_exception; Type: TABLE DATA; Schema: pgagent; Owner: postgres
--

COPY pgagent.pga_exception (jexid, jexscid, jexdate, jextime) FROM stdin;
\.


--
-- Data for Name: pga_joblog; Type: TABLE DATA; Schema: pgagent; Owner: postgres
--

COPY pgagent.pga_joblog (jlgid, jlgjobid, jlgstatus, jlgstart, jlgduration) FROM stdin;
\.


--
-- Data for Name: pga_jobstep; Type: TABLE DATA; Schema: pgagent; Owner: postgres
--

COPY pgagent.pga_jobstep (jstid, jstjobid, jstname, jstdesc, jstenabled, jstkind, jstcode, jstconnstr, jstdbname, jstonerror, jscnextrun) FROM stdin;
\.


--
-- Data for Name: pga_jobsteplog; Type: TABLE DATA; Schema: pgagent; Owner: postgres
--

COPY pgagent.pga_jobsteplog (jslid, jsljlgid, jsljstid, jslstatus, jslresult, jslstart, jslduration, jsloutput) FROM stdin;
\.


--
-- Data for Name: account_snapshots; Type: TABLE DATA; Schema: public; Owner: postgres
--

COPY public.account_snapshots (snapshot_id, account_id, total_assets, available_assets, net_assets, total_position, frozen_assets, margin_balance, margin_used, margin_available, unrealized_pnl, daily_pnl, risk_ratio, "timestamp") FROM stdin;
\.


--
-- Data for Name: accounts; Type: TABLE DATA; Schema: public; Owner: postgres
--

COPY public.accounts (account_id, user_id, platform_id, account_name, api_key, api_secret, passphrase, mt5_id, mt5_server, mt5_primary_pwd, is_mt5_account, is_default, is_active, create_time, update_time, mt5_password, last_sync_time, leverage) FROM stdin;
1ce0146d-b2cb-467d-8b34-ff951e696563	0bc9c5f7-dc77-4f7d-bfbf-4b347a934b24	2	joycar2011@gmail.com	KWL699v3EhZBVxzKOg	EiOw3inPLTVFrTmi0s2zEtTztWmuKfqGvSUg	\N	3971962	Bybit-Live-2	Aq987456!	t	f	t	2026-02-20 10:17:12.238064	2026-02-26 15:20:15.358929	\N	\N	100
c3b7d20d-787a-4bdd-9f92-d73716630bcf	0bc9c5f7-dc77-4f7d-bfbf-4b347a934b24	1	19906779799	DLtsEW0Ei6EVKE6lxlQqsoQ2SGMqcXoWrx97CFB9gVckp8PF87iFxF3URW9S3NSI	fqqLLpgecb2Wb1AsHhx1zxUeNCU1nAKg21k9xnZuETyRJBNRxFuyK99TtAgnCbhp	\N	\N	\N	\N	f	t	t	2026-02-20 10:12:15.609134	2026-02-27 09:43:43.424007	\N	\N	20
\.


--
-- Data for Name: alembic_version; Type: TABLE DATA; Schema: public; Owner: postgres
--

COPY public.alembic_version (version_num) FROM stdin;
20260228_0001
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
\.


--
-- Data for Name: market_data; Type: TABLE DATA; Schema: public; Owner: postgres
--

COPY public.market_data (id, symbol, platform, bid_price, ask_price, mid_price, "timestamp") FROM stdin;
c3f20aa0-4ed4-4e0e-8237-b2587976a5d6	XAUUSDT	binance	5309.72	5309.73	5309.725	2026-03-01 14:53:57.915457
0da79540-2294-455a-884b-b7700a15bb31	XAUUSDT	binance	5309.72	5309.73	5309.725	2026-03-01 14:54:02.935545
80350330-59e1-4793-8c73-14eaf9fa4d15	XAUUSDT	binance	5309.72	5309.73	5309.725	2026-03-01 14:53:57.15722
5037bf72-72e3-4256-9515-8cac5f87ce46	XAUUSDT	binance	5309.72	5309.73	5309.725	2026-03-01 14:54:02.182384
fc7eb607-3f1b-406c-8b22-4ea671e4b9eb	XAUUSDT	binance	5309.72	5309.73	5309.725	2026-03-01 14:53:54.854691
fbbcea80-674f-451b-b30c-0c468c6f86be	XAUUSDT	binance	5309.72	5309.73	5309.725	2026-03-01 14:53:59.960061
6d63f8d4-eb51-4507-b70c-050e864aea6d	XAUUSDT	binance	5309.72	5309.73	5309.725	2026-03-01 14:53:58.211605
b2851cdf-9fb4-4c14-82c5-ac88e5040f11	XAUUSDT	binance	5309.72	5309.73	5309.725	2026-03-01 14:54:03.288492
828403b2-48a6-4f3c-8ae4-9210159f3c9d	XAUUSDT	binance	5309.76	5309.77	5309.765	2026-03-01 14:54:04.999572
6dd9b801-4df4-4782-8431-0f1e5e485557	XAUUSDT	binance	5310.11	5310.12	5310.115	2026-03-01 14:54:07.206343
e885aa03-b081-4fa2-86d6-3af587e9bf43	XAUUSDT	binance	5310.11	5310.12	5310.115	2026-03-01 14:54:07.966198
c639d7ec-7f08-42cd-bd3a-d4bafdc9ad9a	XAUUSDT	binance	5310.15	5310.16	5310.155	2026-03-01 14:54:08.291896
62051999-cf10-48be-9599-cefe87bbc9ae	XAUUSDT	binance	5310.23	5310.24	5310.235	2026-03-01 14:54:10.01389
1e6198b1-2d66-42a9-ad60-2cb8ecf08c3a	XAUUSDT	binance	5310.23	5310.24	5310.235	2026-03-01 14:54:12.241861
507f0426-e295-44e3-9d36-72ae69d652c9	XAUUSDT	binance	5310.23	5310.24	5310.235	2026-03-01 14:54:12.991432
109d06a3-5925-4d4b-9ed8-f83c67afe043	XAUUSDT	binance	5310.23	5310.24	5310.235	2026-03-01 14:54:13.313355
9e8e436b-a3e7-4227-8115-29adf9506c51	XAUUSDT	binance	5310.23	5310.24	5310.235	2026-03-01 14:54:15.010174
76e23a63-2c2d-4b3c-b786-e893b9faf950	XAUUSDT	binance	5310.39	5310.4	5310.395	2026-03-01 14:54:17.255567
108753d0-1f1e-47e7-8645-c6655b6ac154	XAUUSDT	binance	5310.39	5310.4	5310.395	2026-03-01 14:54:17.995103
5a7c4828-9136-44f3-9035-f80434f3d6a3	XAUUSDT	binance	5310.39	5310.4	5310.395	2026-03-01 14:54:18.321236
556b601b-bfd5-4e5e-a250-12120654e587	XAUUSDT	binance	5310.39	5310.4	5310.395	2026-03-01 14:54:20.018817
ed48775a-b848-4ceb-83a6-d7edefc37995	XAUUSDT	binance	5310.39	5310.4	5310.395	2026-03-01 14:54:22.269544
b3b1b3fa-6447-464f-87c6-d9a4a8575e94	XAUUSDT	binance	5310.39	5310.4	5310.395	2026-03-01 14:54:22.985711
ea8de29b-6d79-4a36-bf6c-99bef931cccf	XAUUSDT	binance	5310.39	5310.4	5310.395	2026-03-01 14:54:23.325131
675fc1ca-d5ca-4700-abc7-fb5a02340cf4	XAUUSDT	binance	5310.39	5310.4	5310.395	2026-03-01 14:54:25.020884
85045ffe-090d-4cd9-8f38-83c52bd62444	XAUUSDT	binance	5310.39	5310.4	5310.395	2026-03-01 14:54:27.284797
6e412f6f-cd4e-4e8f-b9b4-6e891392e46e	XAUUSDT	binance	5310.39	5310.4	5310.395	2026-03-01 14:54:27.98673
24b6c41a-06e0-4db0-b122-6ea8207a8ee8	XAUUSDT	binance	5310.39	5310.4	5310.395	2026-03-01 14:54:28.333403
6c871cad-f54f-4f4e-aecf-23c5bd99a3d0	XAUUSDT	binance	5310.39	5310.4	5310.395	2026-03-01 14:54:30.035161
32211b6c-10d9-427a-acaa-c394694aa6f2	XAUUSDT	binance	5310.39	5310.4	5310.395	2026-03-01 14:54:32.29336
04beb5fd-d0a4-4d50-959a-d7092c179a55	XAUUSDT	binance	5310.39	5310.4	5310.395	2026-03-01 14:54:33.00014
68056457-7586-4855-93e3-0fd4841d1d9c	XAUUSDT	binance	5310.39	5310.4	5310.395	2026-03-01 14:54:33.338065
03abbec2-889b-4be8-a9aa-eeeadd07b0f1	XAUUSDT	binance	5310.39	5310.4	5310.395	2026-03-01 14:54:35.040207
3a00ea89-d081-4b38-aba2-ba5facbb53fb	XAUUSDT	binance	5310.39	5310.4	5310.395	2026-03-01 14:54:37.291424
88b6ecd7-ac4f-4b34-b66f-fe3c84928c26	XAUUSDT	binance	5310.39	5310.4	5310.395	2026-03-01 14:54:38.003076
94e4f925-7d95-4070-8994-e5458b7fead6	XAUUSDT	binance	5310.39	5310.4	5310.395	2026-03-01 14:54:38.33546
f248d2e3-5887-4853-82a1-3c512e220d19	XAUUSDT	binance	5310.39	5310.4	5310.395	2026-03-01 14:54:40.049451
99482794-486a-4dc3-8228-13a1d2379915	XAUUSDT	binance	5310.39	5310.4	5310.395	2026-03-01 14:54:42.299408
eb683bfc-69f5-4d81-9ccd-3276a7edc078	XAUUSDT	binance	5310.39	5310.4	5310.395	2026-03-01 14:54:43.00897
8cf0ad61-cde4-4672-9bb6-453a5b0027b9	XAUUSDT	binance	5310.39	5310.4	5310.395	2026-03-01 14:54:43.353341
9f23f8b9-037d-4c6f-b525-560ba759924c	XAUUSDT	binance	5310.39	5310.4	5310.395	2026-03-01 14:54:45.05318
ea91c2ce-9a9e-459c-b8c3-bff4b92653f8	XAUUSDT	binance	5310.39	5310.4	5310.395	2026-03-01 14:54:47.293455
b123e470-d1b7-4b9d-9d6a-40a80119b9e6	XAUUSDT	binance	5310.39	5310.4	5310.395	2026-03-01 14:54:48.01784
62476232-3840-40ec-b059-3cacbb8d26a2	XAUUSDT	binance	5310.39	5310.4	5310.395	2026-03-01 14:54:48.366629
58f665d6-2aa8-46ba-9f54-4b552c88092a	XAUUSDT	binance	5310.39	5310.4	5310.395	2026-03-01 14:54:50.065162
20edd185-d769-4f2d-884a-bc3e7e96bef3	XAUUSDT	binance	5310.39	5310.4	5310.395	2026-03-01 14:54:52.293351
7be546ab-ab98-4156-a8aa-cd45845b5d49	XAUUSDT	binance	5310.39	5310.4	5310.395	2026-03-01 14:54:53.023483
3bda7661-5554-46e7-a2a8-b6b35d363d0b	XAUUSDT	binance	5310.39	5310.4	5310.395	2026-03-01 14:54:53.378201
89ba32b8-4b4f-49cd-be05-e9ca0b1a21c5	XAUUSDT	binance	5310.39	5310.4	5310.395	2026-03-01 14:54:55.06948
fc79c7af-e033-414b-a758-c59039326f94	XAUUSDT	binance	5310.04	5310.05	5310.045	2026-03-01 14:54:57.296309
ddbec5c4-4367-421e-8da1-b42ca0edb207	XAUUSDT	binance	5310.04	5310.05	5310.045	2026-03-01 14:54:58.036112
c15cdebe-2e3a-4bc4-99f0-36553e976c02	XAUUSDT	binance	5310.04	5310.05	5310.045	2026-03-01 14:54:58.384741
f37a6005-092d-4ce0-a635-c9d7463b017a	XAUUSDT	binance	5310.04	5310.05	5310.045	2026-03-01 14:55:00.082636
cfd33561-fd16-4660-b617-5ec4b4efb03c	XAUUSDT	binance	5310.04	5310.05	5310.045	2026-03-01 14:55:02.30115
737a3bd5-c59b-42e7-b42e-f2ac140562dd	XAUUSDT	binance	5310.04	5310.05	5310.045	2026-03-01 14:55:03.053933
926ce8de-93e0-484a-89ef-0cef03e9af5b	XAUUSDT	binance	5310.04	5310.05	5310.045	2026-03-01 14:55:03.396634
100aee31-3b25-4313-9d65-a15a3da10357	XAUUSDT	binance	5309.76	5309.77	5309.765	2026-03-01 14:55:05.099876
1ee7d432-3a34-4118-ac67-56d81bf5df91	XAUUSDT	binance	5309.76	5309.77	5309.765	2026-03-01 14:55:07.346744
63b33adf-b9bc-4adc-bfd2-14fcb797d917	XAUUSDT	binance	5309.76	5309.77	5309.765	2026-03-01 14:55:08.05606
9a59d292-d0b4-4e6e-9ff4-b0ab13af19ba	XAUUSDT	binance	5309.76	5309.77	5309.765	2026-03-01 14:55:08.400757
33138c50-09a9-41ca-b05d-9ef34c76b7f3	XAUUSDT	binance	5309.76	5309.77	5309.765	2026-03-01 14:55:10.105864
4c3c2f87-7625-4fe5-9df8-bc9ec9eff4a2	XAUUSDT	binance	5309.07	5309.08	5309.075	2026-03-01 14:55:12.339894
ac0af7a0-6860-4a26-a0a9-4e2885ad2cd3	XAUUSDT	binance	5309.07	5309.08	5309.075	2026-03-01 14:55:13.067554
3099c9d1-beae-4181-a3b1-d08997922956	XAUUSDT	binance	5309.07	5309.08	5309.075	2026-03-01 14:55:13.408283
075b5215-8d5d-4c65-992c-5cac5688fae2	XAUUSDT	binance	5309.07	5309.08	5309.075	2026-03-01 14:55:15.118637
89362c2e-c639-4aab-9cfe-86c69a34f3fa	XAUUSDT	binance	5309.07	5309.08	5309.075	2026-03-01 14:55:17.342074
a198a314-ceab-4437-9fce-e2110c68c0f8	XAUUSDT	binance	5309.07	5309.08	5309.075	2026-03-01 14:55:18.079233
062be890-1e2d-4279-9178-83bcd28af579	XAUUSDT	binance	5308.56	5308.57	5308.5650000000005	2026-03-01 14:55:18.406545
1400d1ee-4a65-4b5e-8a90-b6d490f9dc8a	XAUUSDT	binance	5308.56	5308.57	5308.5650000000005	2026-03-01 14:55:20.113242
b393c515-cb39-41aa-8c3d-eb3ef2086cdb	XAUUSDT	binance	5308.56	5308.57	5308.5650000000005	2026-03-01 14:55:22.341468
e2f6983e-63fe-401c-8b2a-754a90f84c6b	XAUUSDT	binance	5308.56	5308.57	5308.5650000000005	2026-03-01 14:55:23.082897
6716c18e-713d-465d-8a65-5e9349ff2cc5	XAUUSDT	binance	5308.56	5308.57	5308.5650000000005	2026-03-01 14:55:23.413827
11594961-a220-496e-993b-32770776b24e	XAUUSDT	binance	5308.56	5308.57	5308.5650000000005	2026-03-01 14:55:25.120648
39244daf-4323-4e37-96e7-94e6ba950c39	XAUUSDT	binance	5308.56	5308.57	5308.5650000000005	2026-03-01 14:55:27.33948
d02d32b0-8c77-4ee4-8832-32b08f92703f	XAUUSDT	binance	5308.56	5308.57	5308.5650000000005	2026-03-01 14:55:28.095845
26cc7426-eb6c-4525-82aa-414e087ba6d2	XAUUSDT	binance	5308.56	5308.57	5308.5650000000005	2026-03-01 14:55:28.411115
6345a8c4-23c7-44dc-867c-276cb13af5ff	XAUUSDT	binance	5308.56	5308.57	5308.5650000000005	2026-03-01 14:55:30.131627
cd3113ca-79bb-488e-92b6-8b3a20f35f87	XAUUSDT	binance	5308.56	5308.57	5308.5650000000005	2026-03-01 14:55:32.344158
fe890e86-2506-4b36-9c18-0f842d7455a3	XAUUSDT	binance	5308.56	5308.57	5308.5650000000005	2026-03-01 14:55:33.088258
41621b4c-d623-4c33-be12-e99983e4def0	XAUUSDT	binance	5308.56	5308.57	5308.5650000000005	2026-03-01 14:55:33.409921
b44a7bc0-6599-4f09-bf46-50bceaa4d51b	XAUUSDT	binance	5308.56	5308.57	5308.5650000000005	2026-03-01 14:55:35.149056
46af709f-a1c3-4b01-80f9-ab45b0cdf7b6	XAUUSDT	binance	5308.56	5308.57	5308.5650000000005	2026-03-01 14:55:37.33656
61e73192-b50e-463b-a15b-117ff2650d65	XAUUSDT	binance	5308.56	5308.57	5308.5650000000005	2026-03-01 14:55:38.099027
2c40986c-01f7-4c3c-87c8-0e58d737c810	XAUUSDT	binance	5308.56	5308.57	5308.5650000000005	2026-03-01 14:55:38.42321
1f74bf62-e8db-4b6a-9615-eadc81bba14d	XAUUSDT	binance	5308.56	5308.57	5308.5650000000005	2026-03-01 14:55:40.157443
044a1651-2d65-4f05-a2ba-993ec508f8c0	XAUUSDT	binance	5308.56	5308.57	5308.5650000000005	2026-03-01 14:55:42.339757
aca5973d-d9ed-4214-8075-0b4c5ea609b3	XAUUSDT	binance	5308.56	5308.57	5308.5650000000005	2026-03-01 14:55:43.111638
f2a464bc-30a3-4431-bbb8-78edb0cdcbb9	XAUUSDT	binance	5308.56	5308.57	5308.5650000000005	2026-03-01 14:55:43.407504
5ec77748-6800-4971-94ca-b67b19f76ec8	XAUUSDT	binance	5308.56	5308.57	5308.5650000000005	2026-03-01 14:55:45.159747
1330109e-dbd2-4e14-8174-39cafaf0ca45	XAUUSDT	binance	5308.56	5308.57	5308.5650000000005	2026-03-01 14:55:50.170888
e4086ef9-b5e0-4fa8-bdbe-cdd6911854ea	XAUUSDT	binance	5308.56	5308.57	5308.5650000000005	2026-03-01 14:55:55.180454
61840455-e548-459b-a640-738ef3f03f7c	XAUUSDT	binance	5309.49	5309.5	5309.495	2026-03-01 14:56:00.195278
0125a11f-1068-40d8-bc10-217fb9c95c02	XAUUSDT	binance	5308.56	5308.57	5308.5650000000005	2026-03-01 14:55:47.347561
c9a97266-6575-4938-aefe-acbac717840f	XAUUSDT	binance	5308.56	5308.57	5308.5650000000005	2026-03-01 14:55:52.348793
a05af4cd-651e-413f-9fcb-310d8ed0db49	XAUUSDT	binance	5309.49	5309.5	5309.495	2026-03-01 14:55:57.367705
8ed8edc7-1dbe-42a1-a274-7387c0917ddd	XAUUSDT	binance	5308.56	5308.57	5308.5650000000005	2026-03-01 14:55:48.122424
351c6bbc-0d72-4c3a-aa1b-2407669e74a7	XAUUSDT	binance	5308.56	5308.57	5308.5650000000005	2026-03-01 14:55:53.129711
33ae6caa-53f8-4b81-8546-44b386c728d8	XAUUSDT	binance	5309.49	5309.5	5309.495	2026-03-01 14:55:58.142925
cf216a77-b301-467f-9ea8-b3e72be47c38	XAUUSDT	binance	5308.56	5308.57	5308.5650000000005	2026-03-01 14:55:48.417458
1a380834-7543-4333-8685-e259a9701d6f	XAUUSDT	binance	5308.56	5308.57	5308.5650000000005	2026-03-01 14:55:53.41901
8408b466-d653-4c26-bed8-40bde2be32b2	XAUUSDT	binance	5309.49	5309.5	5309.495	2026-03-01 14:55:58.415091
c49afc10-50af-47ca-b5f8-cb06d22bb42e	XAUUSDT	binance	5309.49	5309.5	5309.495	2026-03-01 14:56:02.382067
916a14a5-ac68-4a53-872a-364abc391b01	XAUUSDT	binance	5309.49	5309.5	5309.495	2026-03-01 14:56:03.14444
21f642eb-2fa2-42a3-b1c5-d0fa3a1151b9	XAUUSDT	binance	5309.49	5309.5	5309.495	2026-03-01 14:56:03.428419
f6212f4c-a608-4c11-8a24-c57bd45f0bbf	XAUUSDT	binance	5308.83	5308.84	5308.835	2026-03-01 14:56:05.203375
38bf1176-e0d5-4375-9052-2c99e4e58300	XAUUSDT	binance	5308.83	5308.84	5308.835	2026-03-01 14:56:07.387841
b9d26311-4c1f-4a26-81f7-fe87f45c919a	XAUUSDT	binance	5308.83	5308.84	5308.835	2026-03-01 14:56:08.161065
4346dca3-210a-40a8-a0f8-cd9580d9e51d	XAUUSDT	binance	5308.83	5308.84	5308.835	2026-03-01 14:56:08.437756
f79c7e98-8b5a-4678-a7b3-2bb065d1f0c6	XAUUSDT	binance	5308.83	5308.84	5308.835	2026-03-01 14:56:10.21046
be08e532-e8ef-4e51-9bef-3e5c1002eafd	XAUUSDT	binance	5308.83	5308.84	5308.835	2026-03-01 14:56:12.387825
3992ff41-44b0-43d0-87a7-a80cdf4a120d	XAUUSDT	binance	5308.83	5308.84	5308.835	2026-03-01 14:56:13.179444
b6d35620-6dc0-4b42-b9a7-594478166c93	XAUUSDT	binance	5308.83	5308.84	5308.835	2026-03-01 14:56:13.446021
eb549377-de0c-4c49-9bc5-911dae02dfd6	XAUUSDT	binance	5308.83	5308.84	5308.835	2026-03-01 14:56:15.227101
50c484f2-8253-4b4d-9bc6-3ba8abf1aae5	XAUUSDT	binance	5308.83	5308.84	5308.835	2026-03-01 14:56:17.388389
35a6ab84-7d65-4919-bdb2-af7eaa3b63ea	XAUUSDT	binance	5308.83	5308.84	5308.835	2026-03-01 14:56:18.188411
d4c3da96-1b3a-47e9-95c5-00f93a458e93	XAUUSDT	binance	5308.83	5308.84	5308.835	2026-03-01 14:56:18.463369
5b596724-4756-4f89-be5b-8bc12f736ad4	XAUUSDT	binance	5308.83	5308.84	5308.835	2026-03-01 14:56:20.236453
4542252a-c28f-4a0b-aea1-02f1ae5476ce	XAUUSDT	binance	5308.83	5308.84	5308.835	2026-03-01 14:56:22.393763
7675fd24-8411-48a1-a24a-492ce64b2488	XAUUSDT	binance	5308.83	5308.84	5308.835	2026-03-01 14:56:23.186262
24edac22-828d-4f9e-92c0-b8c1b6ea912d	XAUUSDT	binance	5308.83	5308.84	5308.835	2026-03-01 14:56:23.450213
9e0e8726-c612-4d98-b219-b18c617701ca	XAUUSDT	binance	5308.83	5308.84	5308.835	2026-03-01 14:56:25.231687
d2691f86-e1f6-4100-bd9b-ab4b85e2102b	XAUUSDT	binance	5308.83	5308.84	5308.835	2026-03-01 14:56:27.404846
90fad483-eca1-4b78-8b17-21e1297a5e76	XAUUSDT	binance	5308.83	5308.84	5308.835	2026-03-01 14:56:28.185148
02f95859-8cc2-45cb-8fe2-8d01feecaa3b	XAUUSDT	binance	5308.83	5308.84	5308.835	2026-03-01 14:56:28.460445
868f0c58-7ada-49a0-957f-6d857614aab5	XAUUSDT	binance	5308.83	5308.84	5308.835	2026-03-01 14:56:30.244203
b73f7a15-f5a2-4216-867f-39401fa8cc8c	XAUUSDT	binance	5308.86	5308.87	5308.865	2026-03-01 14:56:32.413783
cf3aacad-4ab3-45f6-94a5-042245895486	XAUUSDT	binance	5308.86	5308.87	5308.865	2026-03-01 14:56:33.192578
da587825-a59c-4003-b94d-4f4b734e35d4	XAUUSDT	binance	5308.86	5308.87	5308.865	2026-03-01 14:56:33.464833
db26c895-13db-4ee2-9cf3-af251a1d7c86	XAUUSDT	binance	5309.49	5309.5	5309.495	2026-03-01 14:56:35.250053
2ba9a297-61d5-4be8-a793-6c01a7ab8d54	XAUUSDT	binance	5309.49	5309.5	5309.495	2026-03-01 14:56:37.431796
23b61b7c-c7b8-4025-982a-928f40c2b5a3	XAUUSDT	binance	5309.49	5309.5	5309.495	2026-03-01 14:56:38.20245
7bf54f78-388f-44d8-8d2f-2f2e37c8be32	XAUUSDT	binance	5309.49	5309.5	5309.495	2026-03-01 14:56:38.456214
38c43f5e-a20b-4698-ac85-d3ceead4fb71	XAUUSDT	binance	5309.49	5309.5	5309.495	2026-03-01 14:56:40.259266
83b97b1a-eb78-4687-9248-4b5243369654	XAUUSDT	binance	5309.49	5309.5	5309.495	2026-03-01 14:56:42.441153
35bf3580-2dc1-486d-b221-0e4633d83257	XAUUSDT	binance	5309.49	5309.5	5309.495	2026-03-01 14:56:43.221103
4f6c1f43-71ff-4fe8-a21e-f8c055843253	XAUUSDT	binance	5309.49	5309.5	5309.495	2026-03-01 14:56:43.463554
453c15d4-6e9b-449e-9903-2c062f731b34	XAUUSDT	binance	5309.49	5309.5	5309.495	2026-03-01 14:56:45.261805
16009190-1de4-48b0-9649-faa32e149e47	XAUUSDT	binance	5309.49	5309.5	5309.495	2026-03-01 14:56:47.454458
e3374f7d-084a-4530-8ba3-bdf1e19d5c99	XAUUSDT	binance	5309.49	5309.5	5309.495	2026-03-01 14:56:48.217682
b2cb4dfb-d0ea-4986-b256-a76ab639d4d4	XAUUSDT	binance	5309.49	5309.5	5309.495	2026-03-01 14:56:48.451328
dcafd0a6-9d0f-4d62-b066-6392a8a0b6fa	XAUUSDT	binance	5309.49	5309.5	5309.495	2026-03-01 14:56:50.264247
58658f8e-4005-408b-a575-af4cab314768	XAUUSDT	binance	5309.49	5309.5	5309.495	2026-03-01 14:56:52.450498
1981b618-5aa0-479e-93af-36cafabc5202	XAUUSDT	binance	5309.49	5309.5	5309.495	2026-03-01 14:56:53.217468
14470fab-fa60-4be5-a455-21352ba58571	XAUUSDT	binance	5309.49	5309.5	5309.495	2026-03-01 14:56:53.464178
34b0e927-f7dd-427a-9f5a-fdf2c74ab462	XAUUSDT	binance	5309.49	5309.5	5309.495	2026-03-01 14:56:55.262864
c001f13f-0e7b-4ee1-a399-37a14051baa3	XAUUSDT	binance	5309.49	5309.5	5309.495	2026-03-01 14:56:57.458723
27cbdf27-3229-460f-ba95-6a512c7e8026	XAUUSDT	binance	5309.49	5309.5	5309.495	2026-03-01 14:56:58.217336
01dd2025-e702-474e-8f82-9fb8aa3dc196	XAUUSDT	binance	5309.49	5309.5	5309.495	2026-03-01 14:56:58.466015
9d01c1d5-171c-414e-808f-12a182598a60	XAUUSDT	binance	5309.89	5309.9	5309.895	2026-03-01 14:57:00.26528
52159786-2e81-4946-b726-f05e6865ed0d	XAUUSDT	binance	5309.6	5309.61	5309.605	2026-03-01 14:57:02.463014
c1180693-ccc8-4e20-b51c-072bc9306487	XAUUSDT	binance	5309.6	5309.61	5309.605	2026-03-01 14:57:03.216472
f6310595-b16a-4a13-90a1-d29af375d77a	XAUUSDT	binance	5309.6	5309.61	5309.605	2026-03-01 14:57:03.465925
e7d7f334-2d00-4f77-9585-401b40dd1400	XAUUSDT	binance	5309.6	5309.61	5309.605	2026-03-01 14:57:05.269108
d3141d37-ee95-4a3c-b7ca-ee30d7d76a1c	XAUUSDT	binance	5309.58	5309.59	5309.585	2026-03-01 14:57:07.449776
5eae7100-5921-44ce-97fc-80e99645c996	XAUUSDT	binance	5309.58	5309.59	5309.585	2026-03-01 14:57:08.221422
d9567cc8-b1d5-4c47-9ab2-503867e53b3b	XAUUSDT	binance	5309.58	5309.59	5309.585	2026-03-01 14:57:08.45953
0201fa2c-c0ca-411d-b60f-6ae7875528a6	XAUUSDT	binance	5309.58	5309.59	5309.585	2026-03-01 14:57:10.275804
88b7840a-6ee1-4fe4-b744-70dc206c7d77	XAUUSDT	binance	5309.58	5309.59	5309.585	2026-03-01 14:57:12.454836
52c19cdd-2fe9-4665-b1ff-48ffd8ea053c	XAUUSDT	binance	5309.58	5309.59	5309.585	2026-03-01 14:57:13.22731
b271d78f-4bbc-41ea-9f63-421db3ef34ee	XAUUSDT	binance	5309.58	5309.59	5309.585	2026-03-01 14:57:13.454537
872f90b3-11df-4764-8438-5778a45142ef	XAUUSDT	binance	5309.58	5309.59	5309.585	2026-03-01 14:57:15.276577
95d200d1-0b7e-40c2-bba7-423dca6968df	XAUUSDT	binance	5309.6	5309.61	5309.605	2026-03-01 14:57:17.461276
80f9dff3-d887-4159-9b3d-2b93c4d538b9	XAUUSDT	binance	5309.6	5309.61	5309.605	2026-03-01 14:57:18.239809
47bdc98f-da1c-4897-8095-9c99cb89ce28	XAUUSDT	binance	5309.6	5309.61	5309.605	2026-03-01 14:57:18.452264
75b0d171-5dc0-47b4-8d8c-584dff501069	XAUUSDT	binance	5309.72	5309.73	5309.725	2026-03-01 14:57:20.285606
cf832607-deb2-465d-aab5-ea94d7c43301	XAUUSDT	binance	5309.89	5309.9	5309.895	2026-03-01 14:57:22.476905
c320a146-3a48-47d7-a663-868ed6845e1d	XAUUSDT	binance	5309.89	5309.9	5309.895	2026-03-01 14:57:23.25838
991e71f5-c407-44a9-b3ce-800e89166a27	XAUUSDT	binance	5309.89	5309.9	5309.895	2026-03-01 14:57:23.453706
a871e832-ed35-4a35-bef2-3b03befd59f4	XAUUSDT	binance	5309.89	5309.9	5309.895	2026-03-01 14:57:25.305515
c748439f-b33d-4143-b269-7ee5d4c8f13d	XAUUSDT	binance	5309.89	5309.9	5309.895	2026-03-01 14:57:27.493973
52899a94-dde3-4329-be83-acf361576397	XAUUSDT	binance	5309.89	5309.9	5309.895	2026-03-01 14:57:28.257071
e746df5d-c073-4eb8-adf3-1ffe1d8a450d	XAUUSDT	binance	5309.89	5309.9	5309.895	2026-03-01 14:57:28.46187
16dd00cb-e6c2-47d3-bc1c-d402f9eb20a6	XAUUSDT	binance	5309.89	5309.9	5309.895	2026-03-01 14:57:30.32254
8522f035-1a1a-44f3-95de-737a3a9bf761	XAUUSDT	binance	5309.89	5309.9	5309.895	2026-03-01 14:57:32.500946
c82fb2f2-a9b4-47f3-8ff0-cbf10c6e642f	XAUUSDT	binance	5309.89	5309.9	5309.895	2026-03-01 14:57:33.274848
01c0f960-c38e-45a8-af50-a8fb6bccd00f	XAUUSDT	binance	5309.89	5309.9	5309.895	2026-03-01 14:57:33.460496
14104666-4333-4137-b5ca-51aa3de8309b	XAUUSDT	binance	5309.89	5309.9	5309.895	2026-03-01 14:57:35.326882
a477e8af-23c3-4e23-bebd-b42cb1ef9e84	XAUUSDT	binance	5309.89	5309.9	5309.895	2026-03-01 14:57:37.505996
3b61b852-f3db-4e1c-9a5c-c0f109d0d007	XAUUSDT	binance	5309.89	5309.9	5309.895	2026-03-01 14:57:38.279441
4b4c7de6-661b-4ead-8b6a-9faf52ea7d00	XAUUSDT	binance	5309.89	5309.9	5309.895	2026-03-01 14:57:38.474715
9f1de850-cf65-44e2-b739-621b75f648ca	XAUUSDT	binance	5309.89	5309.9	5309.895	2026-03-01 14:57:40.330562
1af35996-2f47-40a9-9b22-bbee9ccb1aed	XAUUSDT	binance	5309.89	5309.9	5309.895	2026-03-01 14:57:42.513138
f14fd550-7404-4ef8-b768-38525fbb05d9	XAUUSDT	binance	5309.89	5309.9	5309.895	2026-03-01 14:57:43.276684
891c2c2d-6a0b-4b36-9812-a06f25792572	XAUUSDT	binance	5309.89	5309.9	5309.895	2026-03-01 14:57:43.486135
76552ad5-7e50-4043-8f88-8b3f740c29ce	XAUUSDT	binance	5309.89	5309.9	5309.895	2026-03-01 14:57:45.336878
99133cf6-2abe-4d66-94ce-9bcd5cb6ade4	XAUUSDT	binance	5309.89	5309.9	5309.895	2026-03-01 14:57:47.51266
6b7c2d20-8cbf-48ec-b3b4-713e365d84a3	XAUUSDT	binance	5309.91	5309.92	5309.915	2026-03-01 14:57:48.277592
9e2c0f5a-0bc3-4e0f-84d8-b4b810ae347d	XAUUSDT	binance	5309.91	5309.92	5309.915	2026-03-01 14:57:53.288925
7edbf8a4-f59b-4a57-9e00-bf0ea6e3d6b6	XAUUSDT	binance	5309.91	5309.92	5309.915	2026-03-01 14:57:58.301836
065e6021-44a3-4e09-a4b5-a0cbafc3ba5a	XAUUSDT	binance	5309.91	5309.92	5309.915	2026-03-01 14:57:48.481442
7b9b743a-0105-4d72-9acc-014512eadc19	XAUUSDT	binance	5309.91	5309.92	5309.915	2026-03-01 14:57:53.493286
7cdf19c9-c181-4cda-97d1-8a104ceb741e	XAUUSDT	binance	5309.91	5309.92	5309.915	2026-03-01 14:57:58.493699
53c3f321-d705-482c-ae3e-3b5d4b90dc5d	XAUUSDT	binance	5309.91	5309.92	5309.915	2026-03-01 14:57:50.347181
48c30ad2-0214-4abf-b8ef-4f0e4c9e142d	XAUUSDT	binance	5309.91	5309.92	5309.915	2026-03-01 14:57:55.34395
fbf4e8c0-68ad-4a6d-8068-a0e4a170d313	XAUUSDT	binance	5309.91	5309.92	5309.915	2026-03-01 14:58:00.3469
3508c92f-1b34-475c-b70b-7883191edb0d	XAUUSDT	binance	5309.91	5309.92	5309.915	2026-03-01 14:57:52.510688
b4f54dbe-bd96-42ef-9eef-ebcc6e2ff8fc	XAUUSDT	binance	5309.91	5309.92	5309.915	2026-03-01 14:57:57.518123
b5643a71-addb-4deb-804f-38169b9086b6	XAUUSDT	binance	5309.91	5309.92	5309.915	2026-03-01 14:58:02.52017
8d3860e3-4f14-4540-b9cc-ce56d7cc79fb	XAUUSDT	binance	5309.91	5309.92	5309.915	2026-03-01 14:58:03.321032
733a05c1-bb07-45a9-81b7-8fb0e6751ef0	XAUUSDT	binance	5309.91	5309.92	5309.915	2026-03-01 14:58:03.490135
48420094-0780-4bfd-afb2-de3efcc45533	XAUUSDT	binance	5309.91	5309.92	5309.915	2026-03-01 14:58:05.355587
d8047435-9012-4f0a-b31e-00fd81e9c9c1	XAUUSDT	binance	5309.91	5309.92	5309.915	2026-03-01 14:58:07.526721
217d38b1-f7af-4db3-90c3-05b2218e7872	XAUUSDT	binance	5309.91	5309.92	5309.915	2026-03-01 14:58:08.327616
31bfbb89-af59-4ff2-98f9-3c5ed36b1c97	XAUUSDT	binance	5309.91	5309.92	5309.915	2026-03-01 14:58:08.497198
599d946f-d02a-4d54-b273-a97c0a430a89	XAUUSDT	binance	5309.91	5309.92	5309.915	2026-03-01 14:58:10.359292
3a9636ae-b6f5-4bbb-b693-f148750b40f5	XAUUSDT	binance	5309.99	5310	5309.995	2026-03-01 14:58:12.535842
78b9d643-7d47-45ee-a02d-642aebf21115	XAUUSDT	binance	5309.99	5310	5309.995	2026-03-01 14:58:13.330178
477dabb9-b499-497c-9974-3604b894e2af	XAUUSDT	binance	5309.99	5310	5309.995	2026-03-01 14:58:13.498501
d40562f0-9b98-437f-9b47-3dd045a4cc6a	XAUUSDT	binance	5309.99	5310	5309.995	2026-03-01 14:58:15.353958
6b8d55e9-b928-422b-9cde-698f3cb09d2d	XAUUSDT	binance	5309.99	5310	5309.995	2026-03-01 14:58:17.542967
1812db25-2633-4b5d-81ec-7f4724a53d7c	XAUUSDT	binance	5309.99	5310	5309.995	2026-03-01 14:58:18.333136
af0a2c68-01e0-4ca1-a01c-465631479f7d	XAUUSDT	binance	5309.99	5310	5309.995	2026-03-01 14:58:18.501797
13f3d99d-0e79-4cf5-9c89-c3e92e1560fc	XAUUSDT	binance	5309.99	5310	5309.995	2026-03-01 14:58:20.36862
3671e5b4-62ab-43aa-ab25-ad8a7a2137a7	XAUUSDT	binance	5309.99	5310	5309.995	2026-03-01 14:58:22.554926
91e1e8f5-753a-4764-80d5-9f4f1fcbbe4e	XAUUSDT	binance	5309.99	5310	5309.995	2026-03-01 14:58:23.341164
65d51ee2-aa77-41b3-920b-9153f26e3402	XAUUSDT	binance	5309.99	5310	5309.995	2026-03-01 14:58:23.496206
112b4f5d-5566-4860-abfe-3f0a1182ec10	XAUUSDT	binance	5309.99	5310	5309.995	2026-03-01 14:58:25.358778
6e369f65-6ad4-48fb-9278-4c3313d63543	XAUUSDT	binance	5309.99	5310	5309.995	2026-03-01 14:58:27.559147
7090019e-355d-4388-8063-b407f4a67b35	XAUUSDT	binance	5309.99	5310	5309.995	2026-03-01 14:58:28.344867
cb269082-1951-49ed-bcdb-325326fb59eb	XAUUSDT	binance	5309.99	5310	5309.995	2026-03-01 14:58:28.489983
1a68e3db-de85-4712-ac1d-be8ec991ce28	XAUUSDT	binance	5310.39	5310.4	5310.395	2026-03-01 14:58:30.367151
4c533583-0e20-4965-8022-8eb197a1bfb2	XAUUSDT	binance	5310.39	5310.4	5310.395	2026-03-01 14:58:32.558679
c5bf69b7-ff4c-4cbb-887e-78be473c6fb2	XAUUSDT	binance	5310.39	5310.4	5310.395	2026-03-01 14:58:33.33732
1986a95c-e447-4efc-bddf-28b6944c10b6	XAUUSDT	binance	5310.39	5310.4	5310.395	2026-03-01 14:58:33.482132
d3611232-ab1a-4237-8714-34a8e18f0352	XAUUSDT	binance	5310.39	5310.4	5310.395	2026-03-01 14:58:35.376133
50cf2c76-35aa-4e52-a363-a969d328a3c2	XAUUSDT	binance	5310.39	5310.4	5310.395	2026-03-01 14:58:37.565911
559496df-e50a-4280-a7e4-53f5e8e6697a	XAUUSDT	binance	5310.03	5310.04	5310.035	2026-03-01 14:58:38.342972
a91ccdcc-f059-4071-a30f-11fecae37e98	XAUUSDT	binance	5310.03	5310.04	5310.035	2026-03-01 14:58:38.480356
e05d77c8-30e7-4f5f-96b5-de1e832020a5	XAUUSDT	binance	5310.03	5310.04	5310.035	2026-03-01 14:58:40.380951
6ea8e702-eaeb-4266-a17f-f4ce85a4392c	XAUUSDT	binance	5310.03	5310.04	5310.035	2026-03-01 14:58:42.564399
f9eabd1b-f8dc-40ab-838c-c212246e636f	XAUUSDT	binance	5310.03	5310.04	5310.035	2026-03-01 14:58:43.34367
25b8b538-6fad-4030-ab1b-d9763b0686f0	XAUUSDT	binance	5310.03	5310.04	5310.035	2026-03-01 14:58:43.481707
84853ae2-baeb-4232-9b87-4a2fa6b26d38	XAUUSDT	binance	5310.03	5310.04	5310.035	2026-03-01 14:58:45.389466
49ec1eca-fded-4b12-9093-60e6af97ecec	XAUUSDT	binance	5310.03	5310.04	5310.035	2026-03-01 14:58:47.560563
54375b1d-5a91-4ae1-b9fb-2d8a986b4f83	XAUUSDT	binance	5310.03	5310.04	5310.035	2026-03-01 14:58:48.323442
f3f5a52c-e10e-446c-b8da-794de0ce89b5	XAUUSDT	binance	5310.03	5310.04	5310.035	2026-03-01 14:58:48.485507
58c80bce-a48b-459e-b5cc-3e614791ace6	XAUUSDT	binance	5310.03	5310.04	5310.035	2026-03-01 14:58:50.406488
935ec528-cf28-4e91-a06c-fd3a76142c7c	XAUUSDT	binance	5310.03	5310.04	5310.035	2026-03-01 14:58:52.564601
2d3bb967-d8e7-442b-a40b-243bbb0d8f41	XAUUSDT	binance	5310.03	5310.04	5310.035	2026-03-01 14:58:53.345934
3d4ecc15-afeb-4816-9573-24de7dcaaf07	XAUUSDT	binance	5310.03	5310.04	5310.035	2026-03-01 14:58:53.481951
ae8be0b3-9299-477e-ab76-c290a7575f78	XAUUSDT	binance	5310.03	5310.04	5310.035	2026-03-01 14:58:55.428701
48912c13-c7a4-4148-a1ca-74b2117cc8ad	XAUUSDT	binance	5310.03	5310.04	5310.035	2026-03-01 14:58:57.560863
f4e42c21-ae69-4944-b0db-9b927bfba81d	XAUUSDT	binance	5310.03	5310.04	5310.035	2026-03-01 14:58:58.339855
8d3a0e53-9087-498b-8988-01e0589f5e66	XAUUSDT	binance	5310.03	5310.04	5310.035	2026-03-01 14:58:58.482277
7e0f89ba-ea1f-464a-abdb-40f62e2a78ae	XAUUSDT	binance	5310.03	5310.04	5310.035	2026-03-01 14:59:00.43824
1ffc22af-9554-43c0-9424-d5d80b48723e	XAUUSDT	binance	5310.03	5310.04	5310.035	2026-03-01 14:59:02.558265
38aaf960-9882-46c5-a6d6-a736e84fb08d	XAUUSDT	binance	5310.03	5310.04	5310.035	2026-03-01 14:59:03.340854
493b42ff-b5e3-407e-b706-d915b4ab8e66	XAUUSDT	binance	5310.03	5310.04	5310.035	2026-03-01 14:59:03.490719
50508381-9daf-46b0-99b2-4098249e250e	XAUUSDT	binance	5310.03	5310.04	5310.035	2026-03-01 14:59:05.437832
32d2293f-d13c-4fdf-ba94-09a7329606c8	XAUUSDT	binance	5310.03	5310.04	5310.035	2026-03-01 14:59:07.566731
982bd607-9750-4517-a67a-aea823fdcf91	XAUUSDT	binance	5310.03	5310.04	5310.035	2026-03-01 14:59:08.337237
00d20565-dd0e-4af5-97ac-72f00fa1d37f	XAUUSDT	binance	5310.03	5310.04	5310.035	2026-03-01 14:59:08.486478
00d73492-20a6-4223-9a33-c8baab18bcde	XAUUSDT	binance	5310.03	5310.04	5310.035	2026-03-01 14:59:10.445921
59de1926-3e32-4d28-a8c6-9813d5a7dbdf	XAUUSDT	binance	5310.05	5310.06	5310.055	2026-03-01 14:59:12.575078
eddd3097-58da-4dc0-b965-fb2c4f1d7383	XAUUSDT	binance	5310.05	5310.06	5310.055	2026-03-01 14:59:13.344511
9a657896-db63-4379-b04b-744a433231b9	XAUUSDT	binance	5310.24	5310.25	5310.245	2026-03-01 14:59:13.490009
7f3cf311-4c19-4021-b001-c4001711b60f	XAUUSDT	binance	5309.91	5309.92	5309.915	2026-03-01 14:59:15.456906
d9b13021-821b-449b-abb9-e1869cc58215	XAUUSDT	binance	5309.91	5309.92	5309.915	2026-03-01 14:59:17.58575
640d6902-91d3-459d-8f4a-66f12c8207dc	XAUUSDT	binance	5309	5309.01	5309.005	2026-03-01 14:59:18.330014
c6ba2575-b3a7-4719-9530-07942590f96b	XAUUSDT	binance	5309	5309.01	5309.005	2026-03-01 14:59:18.491271
29fdd223-c0f2-4783-98ad-4f5efa0d0d38	XAUUSDT	binance	5309.47	5309.48	5309.475	2026-03-01 14:59:20.46873
7848e749-874b-4993-8e9e-5c88fec4ce15	XAUUSDT	binance	5309.52	5309.53	5309.525	2026-03-01 14:59:22.594549
20c213c2-8bfd-4311-8382-2618dda48b13	XAUUSDT	binance	5309.52	5309.53	5309.525	2026-03-01 14:59:23.336155
86fd744e-d89e-4804-872e-836c6cfc90a2	XAUUSDT	binance	5309.52	5309.53	5309.525	2026-03-01 14:59:23.497169
63b296da-2e9b-413f-98f2-f8e3c6725c4d	XAUUSDT	binance	5309.52	5309.53	5309.525	2026-03-01 14:59:25.453368
e1a654de-42a4-4895-85ae-41c40991839c	XAUUSDT	binance	5309.52	5309.53	5309.525	2026-03-01 14:59:27.583785
b2766db9-781a-4e6e-b7ca-4988b70cd8a6	XAUUSDT	binance	5309.27	5309.28	5309.275	2026-03-01 14:59:28.322654
63935f1e-77f3-48f5-8cf6-d8842485a518	XAUUSDT	binance	5309.27	5309.28	5309.275	2026-03-01 14:59:28.502926
692165e4-6c12-4c06-aaa1-e85ccd836469	XAUUSDT	binance	5309.37	5309.41	5309.389999999999	2026-03-01 14:59:30.449477
5c37c923-ab53-4dfa-ae87-0b138825a3bc	XAUUSDT	binance	5309.37	5309.38	5309.375	2026-03-01 14:59:32.596841
61dc3004-1ac7-4fef-a8bd-1e75013d34f0	XAUUSDT	binance	5309.37	5309.38	5309.375	2026-03-01 14:59:33.345584
2c6136cd-2e45-4105-bd32-0eb062262f35	XAUUSDT	binance	5309.37	5309.38	5309.375	2026-03-01 14:59:33.481577
8dbdffd9-7c79-4a04-aa2a-5b2e80c13776	XAUUSDT	binance	5309.37	5309.38	5309.375	2026-03-01 14:59:35.448923
6c91a528-99d8-49d7-8466-fd2f8e89a7dc	XAUUSDT	binance	5309.37	5309.38	5309.375	2026-03-01 14:59:37.579949
716bfc19-6e31-4020-a925-c5c41f61a950	XAUUSDT	binance	5309.37	5309.38	5309.375	2026-03-01 14:59:38.339037
c45b81fd-23b9-4fae-92b1-b4e780ecac1b	XAUUSDT	binance	5309.37	5309.38	5309.375	2026-03-01 14:59:38.492212
fed516cd-9e78-417b-b47c-03d601f87bfb	XAUUSDT	binance	5309.37	5309.38	5309.375	2026-03-01 14:59:40.451038
9e93a2c7-abf1-4d93-ba84-00fea5d5ed62	XAUUSDT	binance	5309.37	5309.38	5309.375	2026-03-01 14:59:42.577255
ab8fd807-1fea-44c0-8699-7cf3ffc4b17c	XAUUSDT	binance	5309.37	5309.38	5309.375	2026-03-01 14:59:43.353971
597872ba-181e-4656-b97e-ccd2e7d4e4bf	XAUUSDT	binance	5309.37	5309.38	5309.375	2026-03-01 14:59:43.479564
e62ec45c-bef7-47c6-8405-7228044871dd	XAUUSDT	binance	5309.37	5309.38	5309.375	2026-03-01 14:59:45.462778
7bb8cdaf-d28d-4d5e-aff9-9fd9851aafd8	XAUUSDT	binance	5309.37	5309.38	5309.375	2026-03-01 14:59:47.579564
a523c2b8-7c90-40c7-83ae-6da38f1d851b	XAUUSDT	binance	5309.37	5309.38	5309.375	2026-03-01 14:59:48.365837
d9f4ddf0-4657-4637-9966-aa894852dfcb	XAUUSDT	binance	5309.37	5309.38	5309.375	2026-03-01 14:59:48.491325
a098ec12-c8e7-489b-9884-e5b7b5287d6f	XAUUSDT	binance	5309.37	5309.38	5309.375	2026-03-01 14:59:53.497202
39324e37-4062-45c8-8f01-f71bf8072fac	XAUUSDT	binance	5309.4	5309.41	5309.405	2026-03-01 14:59:58.483751
6ed96df9-b998-40b3-bd40-4024eade828b	XAUUSDT	binance	5309.37	5309.38	5309.375	2026-03-01 14:59:50.452109
d87485ce-b25d-467c-9ce2-11e20c212b2d	XAUUSDT	binance	5309.37	5309.38	5309.375	2026-03-01 14:59:55.459959
0b30b36d-f1e1-4497-9c17-cefa7c866da8	XAUUSDT	binance	5309.84	5309.85	5309.845	2026-03-01 15:00:00.459288
3a1214ff-a47e-4d0e-8677-d11395a471a6	XAUUSDT	binance	5309.37	5309.38	5309.375	2026-03-01 14:59:52.574913
63f544cc-d5f1-471f-8672-0cacf7e48b00	XAUUSDT	binance	5309.37	5309.38	5309.375	2026-03-01 14:59:57.586539
122e84b1-4605-4c80-8d08-3dae5bf8aef0	XAUUSDT	binance	5309.37	5309.38	5309.375	2026-03-01 14:59:53.377401
36525855-2510-42fb-a7c4-893372e4c782	XAUUSDT	binance	5309.4	5309.41	5309.405	2026-03-01 14:59:58.358263
dfd72248-c3dc-4b6f-83df-cdab473e32c3	XAUUSDT	binance	5309.84	5309.85	5309.845	2026-03-01 15:00:02.582881
30215b5e-e89e-4aec-8f0a-86ec1f2e4ef8	XAUUSDT	binance	5309.84	5309.85	5309.845	2026-03-01 15:00:03.374114
8175790f-7d3c-4aff-98f2-5916f9f706a8	XAUUSDT	binance	5309.84	5309.85	5309.845	2026-03-01 15:00:03.493455
df654821-e333-4c91-a595-62c5a4beab1d	XAUUSDT	binance	5309.84	5309.85	5309.845	2026-03-01 15:00:06.463302
b0f4eb44-72ed-4447-89b3-a5064eb8f7c4	XAUUSDT	binance	5309.84	5309.85	5309.845	2026-03-01 15:00:07.601698
87f1c598-c0d8-4215-9032-90f2a1343e6e	XAUUSDT	binance	5309.45	5309.46	5309.455	2026-03-01 15:00:08.362437
8b7e2aa0-6573-4965-a425-3082b604e066	XAUUSDT	binance	5309.45	5309.46	5309.455	2026-03-01 15:00:08.506312
9ae3514c-cfd9-4242-b3a2-5ea40cb27177	XAUUSDT	binance	5309.45	5309.46	5309.455	2026-03-01 15:00:11.45653
04d9694f-99ad-4792-ad2c-c1df4d6a83c9	XAUUSDT	binance	5309.45	5309.46	5309.455	2026-03-01 15:00:12.611177
9d7fc8a2-0114-4547-bff2-b159ec28f511	XAUUSDT	binance	5309.45	5309.46	5309.455	2026-03-01 15:00:13.38177
70b80634-f25c-49fc-ba0b-f47418226547	XAUUSDT	binance	5309.45	5309.46	5309.455	2026-03-01 15:00:13.513249
d0ed3e07-cc27-4e25-b951-03471a77987a	XAUUSDT	binance	5309.45	5309.46	5309.455	2026-03-01 15:00:16.470214
9b213dbd-6a67-470f-8104-bf0d58b59f1b	XAUUSDT	binance	5309.45	5309.46	5309.455	2026-03-01 15:00:17.62642
667dcd77-9b61-43a4-a94a-a285df8d3c97	XAUUSDT	binance	5309.45	5309.46	5309.455	2026-03-01 15:00:18.393425
ea3084de-d4d7-48ff-b9da-4825683a1ad5	XAUUSDT	binance	5309.45	5309.46	5309.455	2026-03-01 15:00:18.520716
2432646b-58a9-4925-b52a-bbb2e3889871	XAUUSDT	binance	5309.47	5309.48	5309.475	2026-03-01 15:00:21.453148
81ab7cc1-acbe-4338-bbcb-543de53159a7	XAUUSDT	binance	5309.47	5309.48	5309.475	2026-03-01 15:00:22.628064
6c7a655c-9415-483a-972b-310bae613344	XAUUSDT	binance	5309.47	5309.48	5309.475	2026-03-01 15:00:23.392379
ea18605e-7e82-4fb6-86e5-2df1bcadc3f4	XAUUSDT	binance	5309.47	5309.48	5309.475	2026-03-01 15:00:23.517772
1f598013-f0e0-4d07-ad05-de972ab65874	XAUUSDT	binance	5309.47	5309.48	5309.475	2026-03-01 15:00:26.45487
ee01cb48-1db7-4f31-98b3-553188ddf113	XAUUSDT	binance	5309.47	5309.48	5309.475	2026-03-01 15:00:27.611001
904910b2-5e3a-4b20-9a20-96b5ae6a56df	XAUUSDT	binance	5309.47	5309.48	5309.475	2026-03-01 15:00:28.399689
b425b119-2d84-4f9d-a1cc-2042ae4a3e0d	XAUUSDT	binance	5309.47	5309.48	5309.475	2026-03-01 15:00:28.519462
d429dbfc-9060-42bc-83a4-e1e315b48a90	XAUUSDT	binance	5309.47	5309.48	5309.475	2026-03-01 15:00:31.445601
f19ee0e0-91ce-4376-8b44-60dec24d31e7	XAUUSDT	binance	5309.47	5309.48	5309.475	2026-03-01 15:00:32.608915
1bf9cd15-9131-41d5-9318-a5b110469eab	XAUUSDT	binance	5309.47	5309.48	5309.475	2026-03-01 15:00:33.42345
438c699c-650d-4686-b9dd-1b9f92ed1451	XAUUSDT	binance	5309.47	5309.48	5309.475	2026-03-01 15:00:33.517254
89202e33-c546-4e0e-9c31-7ff527f2f406	XAUUSDT	binance	5309.47	5309.48	5309.475	2026-03-01 15:00:36.465572
2c0b04a9-3338-4d92-8f87-c4a2b278d3ac	XAUUSDT	binance	5309.47	5309.48	5309.475	2026-03-01 15:00:37.633945
0e5ed339-d74c-4d49-971f-498ce9aa486e	XAUUSDT	binance	5309.47	5309.48	5309.475	2026-03-01 15:00:38.405591
c7ec6193-46a3-4f88-a455-a0df4d130e93	XAUUSDT	binance	5309.47	5309.48	5309.475	2026-03-01 15:00:38.512249
38ccc2c7-1e24-4910-a5d9-3f25218c6e7d	XAUUSDT	binance	5309.47	5309.48	5309.475	2026-03-01 15:00:41.461534
7c0c3a65-d2cd-4187-9aad-34a49387560b	XAUUSDT	binance	5309.47	5309.48	5309.475	2026-03-01 15:00:42.638703
ffd4eaf1-e250-4931-836f-0590e64ab336	XAUUSDT	binance	5309.47	5309.48	5309.475	2026-03-01 15:00:43.410764
d04e536b-fe0e-4cb0-80f8-5459df4bcf7f	XAUUSDT	binance	5309.47	5309.48	5309.475	2026-03-01 15:00:43.522257
db143f13-5b55-412b-ab72-8f4e63a6979f	XAUUSDT	binance	5309.47	5309.48	5309.475	2026-03-01 15:00:46.452407
877d4e7c-1ae3-4a6f-a3c4-4e8381fce997	XAUUSDT	binance	5309.47	5309.48	5309.475	2026-03-01 15:00:47.653963
20102ed3-1412-4dd3-826b-9b6e88cb5094	XAUUSDT	binance	5309.47	5309.48	5309.475	2026-03-01 15:00:48.400689
7f5386dc-0306-4955-b4b3-8e4783d678e9	XAUUSDT	binance	5309.47	5309.48	5309.475	2026-03-01 15:00:48.539135
8e1df7bc-7ba7-44d8-9854-3d8eb9d930a6	XAUUSDT	binance	5309.47	5309.48	5309.475	2026-03-01 15:00:51.456139
13d7f9d6-911a-4783-912f-70a857a4727a	XAUUSDT	binance	5309.47	5309.48	5309.475	2026-03-01 15:00:52.673323
d2f1da1e-2133-4b8c-8992-7304072fd575	XAUUSDT	binance	5309.47	5309.48	5309.475	2026-03-01 15:00:53.403616
78c15ece-d6e4-4ed4-91fd-fd5678546de0	XAUUSDT	binance	5309.47	5309.48	5309.475	2026-03-01 15:00:53.548379
460e0cc9-b98b-426c-8068-94a7bda07461	XAUUSDT	binance	5309.74	5309.75	5309.745	2026-03-01 15:00:56.449741
b039a9cf-35fa-4ddf-b8f8-408549f13f75	XAUUSDT	binance	5309.74	5309.75	5309.745	2026-03-01 15:00:57.658044
7c897ce9-5b8d-439e-bf2a-cd12143d08a0	XAUUSDT	binance	5309.74	5309.75	5309.745	2026-03-01 15:00:58.40655
d7977219-3a76-4b1f-8d49-f44288402e2f	XAUUSDT	binance	5309.74	5309.75	5309.745	2026-03-01 15:00:58.536123
297e062a-36c4-44d8-8610-98efe681061c	XAUUSDT	binance	5309.74	5309.75	5309.745	2026-03-01 15:01:01.454622
590a5749-6c07-4c9b-a553-223c4a35381b	XAUUSDT	binance	5309.74	5309.75	5309.745	2026-03-01 15:01:02.659582
5bc743ca-a165-4d43-bfb7-ef642ea261a8	XAUUSDT	binance	5310.26	5310.27	5310.265	2026-03-01 15:01:03.416208
51426e8b-e529-4913-adda-2b69c8d0bbf0	XAUUSDT	binance	5309.98	5309.99	5309.985	2026-03-01 15:01:03.542927
4577e1dc-3474-43e6-8ecb-8978462d06d6	XAUUSDT	binance	5309.98	5309.99	5309.985	2026-03-01 15:01:06.453143
0b85fe4c-7312-4a48-afc8-1a47d4913a04	XAUUSDT	binance	5310.15	5310.16	5310.155	2026-03-01 15:01:07.659029
82d8db2f-97cd-4367-9679-73ec6826890e	XAUUSDT	binance	5310.15	5310.16	5310.155	2026-03-01 15:01:08.416432
021ee86b-d117-42de-a4b4-7ad39c10b77a	XAUUSDT	binance	5310.15	5310.16	5310.155	2026-03-01 15:01:08.546472
4c2cef9c-18bf-41ad-a739-ed1cf1fe00d7	XAUUSDT	binance	5310.15	5310.16	5310.155	2026-03-01 15:01:11.456572
46c240a3-a1a9-441c-a1fa-493699f66ca8	XAUUSDT	binance	5310.15	5310.16	5310.155	2026-03-01 15:01:12.648505
624f401a-73ec-4f85-a7cc-9dea78a51b54	XAUUSDT	binance	5310.15	5310.16	5310.155	2026-03-01 15:01:13.416037
daca58d5-9396-4c7d-a988-af2f77d5953a	XAUUSDT	binance	5310.15	5310.16	5310.155	2026-03-01 15:01:13.543162
fc16e0f8-c486-4b12-b0e3-58dbb9bb1563	XAUUSDT	binance	5310.15	5310.16	5310.155	2026-03-01 15:01:16.466077
35727706-96d2-497c-9c25-55a7ff1d4a03	XAUUSDT	binance	5310.15	5310.16	5310.155	2026-03-01 15:01:17.655189
1819ab50-255d-4739-b7ea-abb0ebf0dccf	XAUUSDT	binance	5310.15	5310.16	5310.155	2026-03-01 15:01:18.407773
f0c5bde3-63d1-4501-852c-fa82ae7e2336	XAUUSDT	binance	5310.15	5310.16	5310.155	2026-03-01 15:01:18.54833
23a8ea1c-bf99-440c-bfb8-2d6da09255e0	XAUUSDT	binance	5310.15	5310.16	5310.155	2026-03-01 15:01:21.475106
71a67625-c669-4357-a7fc-79cfadceffbe	XAUUSDT	binance	5310.15	5310.16	5310.155	2026-03-01 15:01:22.661463
f8d1e196-ec26-4b3e-95ce-9ff35b5fc381	XAUUSDT	binance	5310.15	5310.16	5310.155	2026-03-01 15:01:23.421944
ff123663-2f9a-411f-80b1-2f758ec9a52e	XAUUSDT	binance	5310.15	5310.16	5310.155	2026-03-01 15:01:23.525961
4199191f-e27a-4cd0-9973-37df5cffdca8	XAUUSDT	binance	5310.29	5310.3	5310.295	2026-03-01 15:01:26.492093
08efde16-44b9-470c-9041-cd368e84d510	XAUUSDT	binance	5310.29	5310.3	5310.295	2026-03-01 15:01:27.665534
f3dbb691-bc01-4127-a75b-cc262ebcc155	XAUUSDT	binance	5310.29	5310.3	5310.295	2026-03-01 15:01:28.42368
3193dd16-4296-474b-89be-a57ff5449af5	XAUUSDT	binance	5310.29	5310.3	5310.295	2026-03-01 15:01:28.536609
e16b8e15-3825-4a8c-a18a-2c78244c9010	XAUUSDT	binance	5310.29	5310.3	5310.295	2026-03-01 15:01:31.495954
c4667075-4ced-43c4-a100-9524ebbc1d99	XAUUSDT	binance	5310.29	5310.3	5310.295	2026-03-01 15:01:32.674235
3c8ecbf9-cfa6-477d-a965-427a5afce160	XAUUSDT	binance	5310.29	5310.3	5310.295	2026-03-01 15:01:33.407974
ef806994-e606-4c24-9e3a-cb5c53af428e	XAUUSDT	binance	5310.29	5310.3	5310.295	2026-03-01 15:01:33.526339
20868b52-e47d-4b1d-a0d0-ece2a0d463fa	XAUUSDT	binance	5310.29	5310.3	5310.295	2026-03-01 15:01:36.489302
43f7f271-e9a5-46c2-b763-0d50340d568e	XAUUSDT	binance	5310.29	5310.3	5310.295	2026-03-01 15:01:37.648589
d40c1702-df9e-4570-b62d-e20d2e806b3b	XAUUSDT	binance	5310.29	5310.3	5310.295	2026-03-01 15:01:38.403096
bf3f7dbc-9b27-4554-8128-b5a992630e53	XAUUSDT	binance	5310.29	5310.3	5310.295	2026-03-01 15:01:38.548664
da4cdf63-7fbd-4fa3-b42b-eb957ac75006	XAUUSDT	binance	5310.29	5310.3	5310.295	2026-03-01 15:01:41.491494
01c7e797-88dd-4515-8269-48debfa67a4d	XAUUSDT	binance	5310.29	5310.3	5310.295	2026-03-01 15:01:42.66737
4099d255-72f3-4124-8cf9-eb20cbd638ce	XAUUSDT	binance	5310.29	5310.3	5310.295	2026-03-01 15:01:43.412604
e767f8a4-003e-4698-8117-bf0d27bddffe	XAUUSDT	binance	5310.29	5310.3	5310.295	2026-03-01 15:01:43.526467
20bd66be-8060-4613-ae2e-626eb0f0ed35	XAUUSDT	binance	5310.05	5310.06	5310.055	2026-03-01 15:01:46.494264
577d8a4a-30fb-4c2c-9b12-739ebdbf1d95	XAUUSDT	binance	5310.05	5310.06	5310.055	2026-03-01 15:01:47.665451
2dac68cc-2cfb-4081-a6a9-cb2a4d5a8802	XAUUSDT	binance	5310.05	5310.06	5310.055	2026-03-01 15:01:48.418369
18b83c0e-e2c7-430f-9538-85533efa1e39	XAUUSDT	binance	5310.05	5310.06	5310.055	2026-03-01 15:01:48.534895
45f07b4f-81b0-4967-8b80-8f4dba2ff41d	XAUUSDT	binance	5310.14	5310.15	5310.145	2026-03-01 15:01:53.52367
b2ec2278-daa4-413e-9032-bafba82e15ad	XAUUSDT	binance	5310.14	5310.15	5310.145	2026-03-01 15:01:58.535467
35bfd181-9fb0-424c-b922-b8446ea476a2	XAUUSDT	binance	5310.14	5310.15	5310.145	2026-03-01 15:01:51.49235
6551bb8c-d999-4b87-aeb6-6d532aff144e	XAUUSDT	binance	5310.14	5310.15	5310.145	2026-03-01 15:01:56.501957
93237b88-eb0a-4328-b057-5ff73ab6c7ad	XAUUSDT	binance	5310.14	5310.15	5310.145	2026-03-01 15:02:01.503625
ae27a11b-0874-4e90-ba6d-4d649e40bb67	XAUUSDT	binance	5310.14	5310.15	5310.145	2026-03-01 15:01:52.667411
57a87ae7-d439-484a-a201-4e2cccba5d7c	XAUUSDT	binance	5310.14	5310.15	5310.145	2026-03-01 15:01:57.678001
e0b75b8d-ba02-4415-9469-a3769376016a	XAUUSDT	binance	5310.14	5310.15	5310.145	2026-03-01 15:01:53.427551
1540a66e-fca1-4704-af93-de46c8bcaff1	XAUUSDT	binance	5310.14	5310.15	5310.145	2026-03-01 15:01:58.415714
ef2681b6-f5b9-42cf-85b5-c5872e0a3b65	XAUUSDT	binance	5310.19	5310.2	5310.195	2026-03-01 15:02:02.692252
22be8e34-334a-4ea9-858e-a6d103856317	XAUUSDT	binance	5310.19	5310.2	5310.195	2026-03-01 15:02:03.418965
570cdfd3-cb7a-48c1-bbd0-374e7118308b	XAUUSDT	binance	5310.19	5310.2	5310.195	2026-03-01 15:02:03.548676
152b9d09-3e13-4511-a431-390d88ff412b	XAUUSDT	binance	5310.2	5310.21	5310.205	2026-03-01 15:02:06.518622
43075c5a-fb4f-40f3-984f-cfd0afd8e3bd	XAUUSDT	binance	5310.2	5310.21	5310.205	2026-03-01 15:02:07.708731
6f256328-699d-4c59-9a33-224a0f11bbff	XAUUSDT	binance	5310.2	5310.21	5310.205	2026-03-01 15:02:08.423564
9fd5848d-2b99-47ef-9cc6-c21d2294ce58	XAUUSDT	binance	5310.2	5310.21	5310.205	2026-03-01 15:02:08.536212
64e64db3-4923-4c62-a5c0-53683740cbff	XAUUSDT	binance	5309.82	5309.83	5309.825	2026-03-01 15:02:11.548653
5b2f5abf-c719-4751-92ae-d5dd89485e15	XAUUSDT	binance	5309.82	5309.83	5309.825	2026-03-01 15:02:12.704146
95045d9c-41bc-4b69-9741-4ace754b401c	XAUUSDT	binance	5309.82	5309.83	5309.825	2026-03-01 15:02:13.423452
95c09d7e-fff5-4347-b7ba-78ef94c79911	XAUUSDT	binance	5309.82	5309.83	5309.825	2026-03-01 15:02:13.543202
cd6c2240-1a54-4c17-9626-d9f246337663	XAUUSDT	binance	5309.69	5309.7	5309.695	2026-03-01 15:02:16.561664
41dcca44-6e30-4742-b040-33a1ef22a8f5	XAUUSDT	binance	5309.69	5309.7	5309.695	2026-03-01 15:02:17.707047
00470fd6-6d00-49c2-b45d-e4d1bd304dfb	XAUUSDT	binance	5309.69	5309.7	5309.695	2026-03-01 15:02:18.405008
6135cec0-e25f-437c-8278-e19343bab2e9	XAUUSDT	binance	5309.69	5309.7	5309.695	2026-03-01 15:02:18.547726
29bfa1ec-9a3b-4aa8-86d5-6f61496bf11d	XAUUSDT	binance	5309.69	5309.7	5309.695	2026-03-01 15:02:21.569057
24a13f19-e2c0-4b3f-b36d-0bc59b405c6f	XAUUSDT	binance	5310.1	5310.11	5310.105	2026-03-01 15:02:22.711825
5d6fceeb-670b-46aa-a639-8de92f3f6aaa	XAUUSDT	binance	5310.1	5310.11	5310.105	2026-03-01 15:02:23.41479
c75364b1-cf6e-4eaa-96d7-7c1f5487236c	XAUUSDT	binance	5310.1	5310.11	5310.105	2026-03-01 15:02:23.528523
db4e3631-3453-4ee3-be57-c2629ccd0d0c	XAUUSDT	binance	5310.2	5310.21	5310.205	2026-03-01 15:02:26.576566
9a2b7d95-ba62-41e2-a731-861831258d1f	XAUUSDT	binance	5310.2	5310.21	5310.205	2026-03-01 15:02:27.720259
bdebc34a-1dcf-4303-8ad0-cd5692358746	XAUUSDT	binance	5310.2	5310.21	5310.205	2026-03-01 15:02:28.416407
01f05693-46c5-458b-a68c-4271729f3c5b	XAUUSDT	binance	5310.2	5310.21	5310.205	2026-03-01 15:02:28.527898
448c21cd-62b4-40a7-9487-11253f2008b0	XAUUSDT	binance	5310.2	5310.21	5310.205	2026-03-01 15:02:31.593431
88c90bce-3909-4719-bdb8-09b1741d28c4	XAUUSDT	binance	5310.2	5310.21	5310.205	2026-03-01 15:02:32.710896
d32dde97-81c7-49e9-9cfc-951dc86a5b16	XAUUSDT	binance	5310.2	5310.21	5310.205	2026-03-01 15:02:33.412084
5bb82aee-2118-4e29-b1b9-4ed8969eaacb	XAUUSDT	binance	5310.2	5310.21	5310.205	2026-03-01 15:02:33.549554
f36f877d-7544-4e07-b786-e7dfd53885ab	XAUUSDT	binance	5310.36	5310.37	5310.365	2026-03-01 15:02:36.590001
cbf742fb-eeb9-4cef-a7a3-56088ec76f25	XAUUSDT	binance	5310.36	5310.37	5310.365	2026-03-01 15:02:37.7251
314ea9e1-38d2-4d85-b13a-b79570c2f95e	XAUUSDT	binance	5310.36	5310.37	5310.365	2026-03-01 15:02:38.425199
edad4812-2747-4886-ab6d-97ef553fb656	XAUUSDT	binance	5310.36	5310.37	5310.365	2026-03-01 15:02:38.552689
8cd691d2-ce34-492d-8fae-a1f97a768e6a	XAUUSDT	binance	5310.36	5310.37	5310.365	2026-03-01 15:02:41.598456
4e07264a-21df-416d-925b-deb6f4c0d5f5	XAUUSDT	binance	5310.36	5310.37	5310.365	2026-03-01 15:02:42.735913
005e2fd2-2a66-40af-811e-a7bc3a88e25e	XAUUSDT	binance	5310.36	5310.37	5310.365	2026-03-01 15:02:43.417067
d7af45dc-6181-48eb-afe0-5377841cbe41	XAUUSDT	binance	5310.36	5310.37	5310.365	2026-03-01 15:02:43.549113
92e661ae-d6cd-4241-a109-9b241ff8d92e	XAUUSDT	binance	5310.36	5310.37	5310.365	2026-03-01 15:02:46.603959
9726152f-05fb-4b08-98c1-41f33dd46329	XAUUSDT	binance	5310.36	5310.37	5310.365	2026-03-01 15:02:47.737545
a95d3e84-5b48-4405-bf71-86bf2fc06ae2	XAUUSDT	binance	5310.36	5310.37	5310.365	2026-03-01 15:02:48.423377
8a53e679-5281-4a5e-ae23-cb9168625bd0	XAUUSDT	binance	5310.36	5310.37	5310.365	2026-03-01 15:02:48.564276
bb8ce5ea-bfc2-492b-8da4-9fdc0ec675a3	XAUUSDT	binance	5310	5310.01	5310.005	2026-03-01 15:02:51.626608
0f04a834-8105-45eb-b048-befd1305afa2	XAUUSDT	binance	5310	5310.01	5310.005	2026-03-01 15:02:52.73935
354233be-0dcf-407a-a6f8-e1b1794d0296	XAUUSDT	binance	5310	5310.01	5310.005	2026-03-01 15:02:53.436593
afed02d1-4cb3-42f1-9313-7b2ebeda9a10	XAUUSDT	binance	5310	5310.01	5310.005	2026-03-01 15:02:53.565443
d2c6487b-e5ba-4919-946c-a1ac9c91cf67	XAUUSDT	binance	5310	5310.01	5310.005	2026-03-01 15:02:56.626986
054dae10-b4ce-47e4-af51-62005e2ee190	XAUUSDT	binance	5310	5310.01	5310.005	2026-03-01 15:02:57.728043
2b20a8ac-53a5-4dcb-bffd-815593b40067	XAUUSDT	binance	5310	5310.01	5310.005	2026-03-01 15:02:58.437708
cf78ae24-26d4-46b9-8588-e5c1dfb18c4c	XAUUSDT	binance	5310	5310.01	5310.005	2026-03-01 15:02:58.579794
da389217-346f-4300-b530-8bf4c2ba9a88	XAUUSDT	binance	5310	5310.01	5310.005	2026-03-01 15:03:01.6283
9a013c0a-54ac-4509-b51b-a8af0300e070	XAUUSDT	binance	5310	5310.01	5310.005	2026-03-01 15:03:02.737921
22b2ef6e-6779-4ad2-bb43-35cdb015c76d	XAUUSDT	binance	5310	5310.01	5310.005	2026-03-01 15:03:03.428884
05201f43-9522-4b4b-a04f-4a0621898b1e	XAUUSDT	binance	5310	5310.01	5310.005	2026-03-01 15:03:03.574615
889946a1-49b6-4ac3-a186-9e4167fcbe78	XAUUSDT	binance	5310	5310.01	5310.005	2026-03-01 15:03:06.625041
24cfb6fc-2d81-441d-80c5-69e7f14b59eb	XAUUSDT	binance	5310	5310.01	5310.005	2026-03-01 15:03:07.735696
f02c5779-f4d6-4146-8962-7a45029bf399	XAUUSDT	binance	5310	5310.01	5310.005	2026-03-01 15:03:08.444125
b532615b-e287-42b2-888d-bf0b608415d7	XAUUSDT	binance	5310	5310.01	5310.005	2026-03-01 15:03:08.573333
1760a29e-f7d9-4b01-b9cb-3b803b6e7014	XAUUSDT	binance	5310	5310.01	5310.005	2026-03-01 15:03:11.62171
cd8b3d34-09a5-48b7-bc20-d671be306161	XAUUSDT	binance	5310	5310.01	5310.005	2026-03-01 15:03:12.735846
d4917ac9-c7ad-4d06-95ae-eea8d47b19fd	XAUUSDT	binance	5310	5310.01	5310.005	2026-03-01 15:03:13.443616
637a5c0c-91d2-4dea-98b0-2b3a8a4f16f8	XAUUSDT	binance	5310	5310.01	5310.005	2026-03-01 15:03:13.571677
ea6c79c8-f29f-4ae2-9a42-0145616df30a	XAUUSDT	binance	5310	5310.01	5310.005	2026-03-01 15:03:16.616874
40584177-a58d-48ef-a182-65dbac00de6d	XAUUSDT	binance	5310	5310.01	5310.005	2026-03-01 15:03:17.737881
f464568d-e7b8-4613-beb6-b6eba75455ab	XAUUSDT	binance	5310	5310.01	5310.005	2026-03-01 15:03:18.460179
f09e0515-be0c-4ef5-9b70-881d7252b678	XAUUSDT	binance	5310	5310.01	5310.005	2026-03-01 15:03:18.580619
16823f5d-506e-4e7c-915f-99d0887db892	XAUUSDT	binance	5310.03	5310.04	5310.035	2026-03-01 15:03:21.627448
f027d97e-15e0-4976-b02a-ea08b40de0ec	XAUUSDT	binance	5310.03	5310.04	5310.035	2026-03-01 15:03:22.728952
310dbc95-b244-42d8-bb8c-0814ad99994f	XAUUSDT	binance	5310.03	5310.04	5310.035	2026-03-01 15:03:23.472373
7ff1ef4e-295a-46da-bc28-a44f1a1ae1ea	XAUUSDT	binance	5310.03	5310.04	5310.035	2026-03-01 15:03:23.583775
9659b326-64be-4b35-97a1-175999d38bcf	XAUUSDT	binance	5310.03	5310.04	5310.035	2026-03-01 15:03:26.630166
0b5be8a9-a1ac-4def-a269-fed2b5504835	XAUUSDT	binance	5310.03	5310.04	5310.035	2026-03-01 15:03:27.736974
6d4b32d0-ad84-47f7-9b55-369335320a94	XAUUSDT	binance	5310.03	5310.04	5310.035	2026-03-01 15:03:28.484851
2b96be81-d945-4cd6-b342-f3c7cb8991ea	XAUUSDT	binance	5310.03	5310.04	5310.035	2026-03-01 15:03:28.573212
9b73d628-2d2d-4e8f-81a6-71148faf65c0	XAUUSDT	binance	5310.03	5310.04	5310.035	2026-03-01 15:03:31.629691
b032ebc7-7cca-4865-bc0c-6137bbca1a48	XAUUSDT	binance	5310.03	5310.04	5310.035	2026-03-01 15:03:32.738286
6d26a5be-38d8-4ae7-8717-6f97b41d903a	XAUUSDT	binance	5310.03	5310.04	5310.035	2026-03-01 15:03:33.488869
389c7459-8033-4b26-bf27-bf412ad19414	XAUUSDT	binance	5310.03	5310.04	5310.035	2026-03-01 15:03:33.584486
1fb67f0f-a720-44ab-8106-6b93087f0698	XAUUSDT	binance	5310.03	5310.04	5310.035	2026-03-01 15:03:36.621357
c78c2c02-7dfe-42c4-95d3-b38dfff4b8ab	XAUUSDT	binance	5310.03	5310.04	5310.035	2026-03-01 15:03:37.735999
59f8cddf-6c8d-4481-9042-18e2fe6f0b55	XAUUSDT	binance	5310.03	5310.04	5310.035	2026-03-01 15:03:38.485735
e79eac6d-71f9-4ae3-923e-745d7b857b1f	XAUUSDT	binance	5310.03	5310.04	5310.035	2026-03-01 15:03:38.59857
9022dc6d-4f45-4087-a0d1-8b5f4a04cb7c	XAUUSDT	binance	5310.03	5310.04	5310.035	2026-03-01 15:03:41.636565
b72a6126-26a9-45c6-a282-9ecb389b1a91	XAUUSDT	binance	5310.03	5310.04	5310.035	2026-03-01 15:03:42.741139
c4884502-74db-48c4-bddf-9fd9d767c290	XAUUSDT	binance	5310.03	5310.04	5310.035	2026-03-01 15:03:43.490434
2fb5d10a-b55f-4003-b4d2-bf740045e068	XAUUSDT	binance	5310.03	5310.04	5310.035	2026-03-01 15:03:43.60619
73206d80-c6bd-48da-b8b2-ca595aa9fc59	XAUUSDT	binance	5309.5	5309.51	5309.505	2026-03-01 15:03:46.640455
c39dbf62-57c6-46a7-9f71-2345f1cec75c	XAUUSDT	binance	5309.5	5309.51	5309.505	2026-03-01 15:03:47.737003
c94f4500-256a-4a92-8508-a2ac820c4e82	XAUUSDT	binance	5309.5	5309.51	5309.505	2026-03-01 15:03:48.507454
2fe7af1f-5b85-4705-a105-92c0bd1ed80e	XAUUSDT	binance	5309.5	5309.51	5309.505	2026-03-01 15:03:48.603176
90b31bf4-ca4b-46aa-b941-30f5f15590e1	XAUUSDT	binance	5309.5	5309.51	5309.505	2026-03-01 15:03:53.613656
a081ea70-eaa8-421f-89d7-af4215d9ccec	XAUUSDT	binance	5309.2	5309.21	5309.205	2026-03-01 15:03:58.614529
1f42897c-be80-4cd3-a239-36ca8c22fe9a	XAUUSDT	binance	5309.5	5309.51	5309.505	2026-03-01 15:03:51.655136
120ded56-a9ab-4137-9d11-b1a75c5a7dd5	XAUUSDT	binance	5309.2	5309.21	5309.205	2026-03-01 15:03:56.65475
98dafafa-b798-4f6f-8003-d69bf60ebc0f	XAUUSDT	binance	5308.84	5308.85	5308.845	2026-03-01 15:04:01.651518
c70e61f8-4385-4da4-8339-53f38e34236a	XAUUSDT	binance	5309.5	5309.51	5309.505	2026-03-01 15:03:52.737927
fcba6e4c-1554-4a07-b26d-870fb042ae45	XAUUSDT	binance	5309.2	5309.21	5309.205	2026-03-01 15:03:57.737686
3dd9dc37-a5b2-4b0c-b887-503879d369d0	XAUUSDT	binance	5309.5	5309.51	5309.505	2026-03-01 15:03:53.512051
57ec4aad-3c37-4499-9205-df216a45c5f8	XAUUSDT	binance	5309.2	5309.21	5309.205	2026-03-01 15:03:58.518397
17cb90dc-5282-4ff4-93ec-4b9c9066ca0e	XAUUSDT	binance	5308.84	5308.85	5308.845	2026-03-01 15:04:02.736069
d6d041b5-e522-4e8f-b084-18ce634efea5	XAUUSDT	binance	5308.84	5308.85	5308.845	2026-03-01 15:04:03.514039
06a2b320-6f70-4442-b1d1-f6eae2f98eff	XAUUSDT	binance	5308.84	5308.85	5308.845	2026-03-01 15:04:03.612203
f14bbae2-2d64-41be-9c20-14fd42f8b610	XAUUSDT	binance	5308.84	5308.85	5308.845	2026-03-01 15:04:06.660435
b22fcca8-fe8b-4472-8001-82ef29097835	XAUUSDT	binance	5308.84	5308.85	5308.845	2026-03-01 15:04:07.726949
94d52b4b-3a66-47a2-bbec-d367405a297e	XAUUSDT	binance	5308.84	5308.85	5308.845	2026-03-01 15:04:08.51336
9d31e4d2-53bf-4fe8-9178-82759f3d7273	XAUUSDT	binance	5308.84	5308.85	5308.845	2026-03-01 15:04:08.62521
3456e894-cb98-4f3f-925b-9661fcbb3383	XAUUSDT	binance	5308.84	5308.85	5308.845	2026-03-01 15:04:11.660382
5a8e95c6-0875-4a9c-8d91-e06e0a5acb3c	XAUUSDT	binance	5308.84	5308.85	5308.845	2026-03-01 15:04:12.726827
34ced635-6c71-4958-91a4-e13299b15ab4	XAUUSDT	binance	5308.84	5308.85	5308.845	2026-03-01 15:04:13.519858
e8889128-094e-4127-beca-dd4d6b3e94b0	XAUUSDT	binance	5308.84	5308.85	5308.845	2026-03-01 15:04:13.621758
6a9df287-3c87-4963-9ce4-9c473413a2dd	XAUUSDT	binance	5308.84	5308.85	5308.845	2026-03-01 15:04:16.651
806f23f6-6560-4e66-b637-9c2cd0816c51	XAUUSDT	binance	5308.84	5308.85	5308.845	2026-03-01 15:04:17.727908
d7deb31a-3f14-4bd8-b398-007959c5c565	XAUUSDT	binance	5308.84	5308.85	5308.845	2026-03-01 15:04:18.521654
1312ff3d-4f17-4d5d-9eff-5c8e2885b097	XAUUSDT	binance	5308.84	5308.85	5308.845	2026-03-01 15:04:18.617342
cce74ba3-ce91-4e8e-88a4-92bec8b591e4	XAUUSDT	binance	5308.84	5308.85	5308.845	2026-03-01 15:04:21.657999
d7785c86-7acd-4600-8d0c-d37c64556c9d	XAUUSDT	binance	5308.84	5308.85	5308.845	2026-03-01 15:04:22.741079
745ff1d4-4ff4-47ff-9226-12ecea3fa704	XAUUSDT	binance	5308.84	5308.85	5308.845	2026-03-01 15:04:23.533007
006fd1e2-703c-4003-86b7-27625c60b250	XAUUSDT	binance	5308.84	5308.85	5308.845	2026-03-01 15:04:23.62832
d46d803a-6775-4478-b741-2df45334fffd	XAUUSDT	binance	5308.84	5308.85	5308.845	2026-03-01 15:04:26.646826
19d0bf4b-2a3c-434d-a621-d9deb9aba5e6	XAUUSDT	binance	5308.84	5308.85	5308.845	2026-03-01 15:04:27.746218
871aa9dd-7efe-4a15-bdd7-7b6b0445c356	XAUUSDT	binance	5308.75	5308.76	5308.755	2026-03-01 15:04:28.536149
0aec3f0c-7685-48e1-8ed9-a4af1325ec63	XAUUSDT	binance	5308.75	5308.76	5308.755	2026-03-01 15:04:28.631967
75a29e19-1e3f-4a68-bb5a-85393779f186	XAUUSDT	binance	5308.41	5308.42	5308.415	2026-03-01 15:04:31.652832
e95399a9-9f18-4c65-9061-6d20b0f63b01	XAUUSDT	binance	5308.41	5308.42	5308.415	2026-03-01 15:04:32.766964
7065f90d-b5b4-4c3d-a965-08de009a6afb	XAUUSDT	binance	5308.41	5308.42	5308.415	2026-03-01 15:04:33.552968
e830fdd3-ec4f-4ebb-9f14-f406a678a19a	XAUUSDT	binance	5308.41	5308.42	5308.415	2026-03-01 15:04:33.648365
431b26bb-e39c-46e3-9164-6e7f11bdf7e3	XAUUSDT	binance	5308.41	5308.42	5308.415	2026-03-01 15:04:36.661532
dfe28e6f-96ee-470c-8fc9-acd3562606a0	XAUUSDT	binance	5308.71	5308.72	5308.715	2026-03-01 15:04:37.767286
eb271685-a3a4-4f3e-843a-d0728ec0841a	XAUUSDT	binance	5308.71	5308.72	5308.715	2026-03-01 15:04:38.564179
70591917-dd8a-40f4-b8e0-5b3a39539ef6	XAUUSDT	binance	5308.71	5308.72	5308.715	2026-03-01 15:04:38.659426
f286226a-7bad-4d6c-97a1-7bd376eb05f2	XAUUSDT	binance	5308.42	5308.43	5308.425	2026-03-01 15:04:41.648149
9f4e85b7-1280-4cc7-8e86-6f36e5a51573	XAUUSDT	binance	5308.42	5308.43	5308.425	2026-03-01 15:04:42.760858
2d087fa8-30b7-4334-9b8d-f6d00c3771d7	XAUUSDT	binance	5308.42	5308.43	5308.425	2026-03-01 15:04:43.562443
56856b26-f182-412c-840c-d8afc8ba0fa2	XAUUSDT	binance	5308.42	5308.43	5308.425	2026-03-01 15:04:43.657829
caade211-e254-4475-ac9d-bd9cb3c46179	XAUUSDT	binance	5308.42	5308.43	5308.425	2026-03-01 15:04:46.661448
e7976385-5e9d-4d10-b323-8b78ede0c041	XAUUSDT	binance	5308.41	5308.42	5308.415	2026-03-01 15:04:47.763592
b2b0f2f7-bce5-4394-9d6a-c8263ad32165	XAUUSDT	binance	5308.41	5308.42	5308.415	2026-03-01 15:04:48.560463
b5108d37-fddb-43c5-b8f5-664392a24a8c	XAUUSDT	binance	5308.41	5308.42	5308.415	2026-03-01 15:04:48.659317
7914cac4-8baf-4e7b-902c-77939be1bd7f	XAUUSDT	binance	5308.41	5308.42	5308.415	2026-03-01 15:04:51.657506
2d320fbb-f2d8-4faa-bdaa-09fe03bab970	XAUUSDT	binance	5308.41	5308.42	5308.415	2026-03-01 15:04:52.760275
193e28fa-bbb8-497a-b841-bfb2a4c8123d	XAUUSDT	binance	5308.41	5308.42	5308.415	2026-03-01 15:04:53.567595
790dd1f3-8a93-4a09-b659-d43a87880238	XAUUSDT	binance	5308.41	5308.42	5308.415	2026-03-01 15:04:53.663279
e5d42508-be2d-41b7-a915-a0951225c511	XAUUSDT	binance	5308.41	5308.42	5308.415	2026-03-01 15:04:56.656537
eaff4108-82a1-4fdf-846b-22bc53106e52	XAUUSDT	binance	5308.41	5308.42	5308.415	2026-03-01 15:04:57.767102
b3fc89bd-7486-4104-b385-373d06357d2c	XAUUSDT	binance	5308.41	5308.42	5308.415	2026-03-01 15:04:58.560815
f014ff7f-c5ae-49f3-99f5-ede07f27f4fb	XAUUSDT	binance	5308.41	5308.42	5308.415	2026-03-01 15:04:58.679655
c7437d9b-1565-4b8b-b9b9-ceb3e263a0c0	XAUUSDT	binance	5308.41	5308.42	5308.415	2026-03-01 15:05:01.673289
9ab38a4d-84bf-4da6-924c-23196820ddc9	XAUUSDT	binance	5308.41	5308.42	5308.415	2026-03-01 15:05:02.78305
e38f72eb-72d0-43ca-864d-ed8e0c044548	XAUUSDT	binance	5308.41	5308.42	5308.415	2026-03-01 15:05:03.561939
026b82c1-aa29-4b3b-b96e-e5d46cfcd055	XAUUSDT	binance	5308.41	5308.42	5308.415	2026-03-01 15:05:03.688848
e289df47-f134-4a62-b643-b8970791512f	XAUUSDT	binance	5308.12	5308.13	5308.125	2026-03-01 15:05:06.660618
ae806d6d-e3db-4e55-b365-b051f66ddb03	XAUUSDT	binance	5308.12	5308.13	5308.125	2026-03-01 15:05:07.792161
21700f75-374d-45d0-bf6b-12ea7fe061bb	XAUUSDT	binance	5308.12	5308.13	5308.125	2026-03-01 15:05:08.562329
907574ba-d143-498a-9a2e-952652007853	XAUUSDT	binance	5308.12	5308.13	5308.125	2026-03-01 15:05:08.707578
e29fe1aa-dc15-45d9-ad19-eb8911056e21	XAUUSDT	binance	5308.12	5308.13	5308.125	2026-03-01 15:05:11.679525
463e12ae-a0a6-4c83-92fc-104ba9bce6dc	XAUUSDT	binance	5308.12	5308.13	5308.125	2026-03-01 15:05:12.771975
22c014e4-be93-4861-adad-e08f82216dae	XAUUSDT	binance	5308.12	5308.13	5308.125	2026-03-01 15:05:13.565963
e6ae78ac-a895-436c-ba48-50a339ddc342	XAUUSDT	binance	5308.12	5308.13	5308.125	2026-03-01 15:05:13.72254
419c581f-86db-496a-b094-5fc94e08b8f6	XAUUSDT	binance	5308.12	5308.13	5308.125	2026-03-01 15:05:16.686545
a4b15292-1d99-4519-8da1-e4fb16a11cfb	XAUUSDT	binance	5308.12	5308.13	5308.125	2026-03-01 15:05:17.789178
3d5b6683-18f5-4acb-8494-6b923c8dd575	XAUUSDT	binance	5308	5308.01	5308.005	2026-03-01 15:05:18.567492
1e69eebf-1e7c-481f-b871-a6149c7d09a8	XAUUSDT	binance	5308	5308.01	5308.005	2026-03-01 15:05:18.711496
93e057e3-c792-44de-b94f-a6daaa15985d	XAUUSDT	binance	5307.66	5307.67	5307.665	2026-03-01 15:05:21.692792
2501f57f-ca35-454f-acb6-5e5d25e0402d	XAUUSDT	binance	5307.66	5307.67	5307.665	2026-03-01 15:05:22.801775
cd6cb6a4-5daf-4862-a4c4-5fe37ae9c2e8	XAUUSDT	binance	5307.66	5307.67	5307.665	2026-03-01 15:05:23.559655
88bf623e-364b-4fa1-99aa-2f24fc576407	XAUUSDT	binance	5307.66	5307.67	5307.665	2026-03-01 15:05:23.714016
cf9e3856-1334-408b-8dd1-bae0deaf6c1e	XAUUSDT	binance	5307.66	5307.67	5307.665	2026-03-01 15:05:26.690049
9ad60c6c-402d-4aa4-b5f3-d626cd236cf3	XAUUSDT	binance	5307.66	5307.67	5307.665	2026-03-01 15:05:27.787522
16a9381a-d297-45e4-94d7-01ff671ae499	XAUUSDT	binance	5307.66	5307.67	5307.665	2026-03-01 15:05:28.559601
10bf1915-1e70-4c77-bcea-a72785507f47	XAUUSDT	binance	5307.66	5307.67	5307.665	2026-03-01 15:05:28.71881
f9838b09-ae10-4e43-ac7d-04e7361df436	XAUUSDT	binance	5307.87	5307.88	5307.875	2026-03-01 15:05:31.681071
a056c3a6-4b8b-408d-84a1-81ed0e38d5c3	XAUUSDT	binance	5307.87	5307.88	5307.875	2026-03-01 15:05:32.785193
d024b51c-3acd-4e76-9450-5d561fbc073b	XAUUSDT	binance	5307.87	5307.88	5307.875	2026-03-01 15:05:33.556507
8b52942f-c5ab-47ef-97b5-5f0c7486e358	XAUUSDT	binance	5307.87	5307.88	5307.875	2026-03-01 15:05:33.698583
f7509a10-be74-49f0-b416-7ef1f76dbc8e	XAUUSDT	binance	5307.8	5307.81	5307.805	2026-03-01 15:05:36.70434
0ac68017-f303-483e-aeea-0bebbff38a42	XAUUSDT	binance	5307.69	5307.7	5307.695	2026-03-01 15:05:37.796278
e602aac1-8b6f-4d9d-8812-632af951e76e	XAUUSDT	binance	5307.69	5307.7	5307.695	2026-03-01 15:05:38.566656
9d7c60ba-26ef-413b-af06-efdc9bf5a9ab	XAUUSDT	binance	5307.69	5307.7	5307.695	2026-03-01 15:05:38.704525
b27c32cf-530a-4b64-b567-b700011c2526	XAUUSDT	binance	5307.69	5307.7	5307.695	2026-03-01 15:05:41.712158
6234e561-21c5-4305-a78b-69c93b2c6b83	XAUUSDT	binance	5307.69	5307.7	5307.695	2026-03-01 15:05:42.808909
1d65c34b-bf2f-42b0-8a36-a550a379cd47	XAUUSDT	binance	5307.69	5307.7	5307.695	2026-03-01 15:05:43.570504
dbc118fb-e681-4dca-8f4b-80778d0aa767	XAUUSDT	binance	5307.69	5307.7	5307.695	2026-03-01 15:05:43.700587
6988fed9-c3f2-4e47-92cd-d5b2985e97fa	XAUUSDT	binance	5307.69	5307.7	5307.695	2026-03-01 15:05:46.711102
c7e5e2ed-98c4-4dce-89c5-e61bc0e0214f	XAUUSDT	binance	5307.69	5307.7	5307.695	2026-03-01 15:05:47.804535
97c55444-766d-4fd6-8bcf-627e2d6b305f	XAUUSDT	binance	5307.69	5307.7	5307.695	2026-03-01 15:05:48.580822
78a5ab60-fbef-4cae-8947-e5262d677dd7	XAUUSDT	binance	5307.69	5307.7	5307.695	2026-03-01 15:05:48.708393
058decc6-5b12-4e04-828e-007df0fa04df	XAUUSDT	binance	5307.72	5307.73	5307.725	2026-03-01 15:05:53.711195
aa665ff4-6663-4f55-ad6a-581c92072894	XAUUSDT	binance	5307.84	5307.85	5307.845	2026-03-01 15:05:58.722695
9b6a8643-5c86-449d-928b-36dac5436801	XAUUSDT	binance	5307.97	5307.98	5307.975	2026-03-01 15:06:03.725539
9d0607f7-5ec0-4d1b-89bb-0828f2d56e0a	XAUUSDT	binance	5307.97	5307.98	5307.975	2026-03-01 15:06:08.737366
4959c53c-538a-4819-89d2-59df6cc79703	XAUUSDT	binance	5307.97	5307.98	5307.975	2026-03-01 15:06:13.751192
1dbcf9ce-d1b1-4962-8be3-8efc77807d95	XAUUSDT	binance	5307.84	5307.85	5307.845	2026-03-01 15:06:18.759369
6800f9d2-f924-48cf-98bb-9e3c9f1cfa5d	XAUUSDT	binance	5307.64	5307.65	5307.645	2026-03-01 15:06:23.771115
76f7bfbd-311f-46c3-b0a9-b8181f10719e	XAUUSDT	binance	5307.64	5307.65	5307.645	2026-03-01 15:06:28.770766
f459d879-71a5-4743-bce0-0fe284189b59	XAUUSDT	binance	5307.6	5307.61	5307.605	2026-03-01 15:06:33.786496
61e55ad7-fcf2-4420-aeef-1d06af7dc3e0	XAUUSDT	binance	5307.6	5307.61	5307.605	2026-03-01 15:06:38.790286
44d24301-7e80-4268-b7b1-e2badad82844	XAUUSDT	binance	5307.6	5307.61	5307.605	2026-03-01 15:06:43.806552
7d3b8dc1-4116-4090-a814-d834674d5408	XAUUSDT	binance	5307.6	5307.61	5307.605	2026-03-01 15:06:48.815807
0e3482e9-6deb-4df0-9afe-9c9f67073d29	XAUUSDT	binance	5307.64	5307.65	5307.645	2026-03-01 15:06:53.830982
b9efc5bb-5c72-431d-8bc0-22f116b5309f	XAUUSDT	binance	5307.64	5307.65	5307.645	2026-03-01 15:06:58.820848
47833dc1-5709-486b-9220-ea7b2d2452e8	XAUUSDT	binance	5307.69	5307.7	5307.695	2026-03-01 15:05:51.704605
8155ab3f-91c8-46ff-b1f6-1ccc11ab1569	XAUUSDT	binance	5307.84	5307.85	5307.845	2026-03-01 15:05:56.704575
00f49c89-abf9-46d5-bdb7-dd56f1e0749e	XAUUSDT	binance	5307.97	5307.98	5307.975	2026-03-01 15:06:01.701422
2fbf144d-cff8-46c1-b537-7482c08215e3	XAUUSDT	binance	5307.97	5307.98	5307.975	2026-03-01 15:06:06.708881
78897fbe-63b1-4a4a-a63d-194b60fefffb	XAUUSDT	binance	5307.97	5307.98	5307.975	2026-03-01 15:06:11.714893
7027a54b-fa7a-4b5a-9b03-53156b1def32	XAUUSDT	binance	5307.97	5307.98	5307.975	2026-03-01 15:06:16.73233
ee2b1ae1-4683-4ed8-be75-ad46d6d41462	XAUUSDT	binance	5307.64	5307.65	5307.645	2026-03-01 15:06:21.745304
6d58a640-80b1-4806-8e04-f05498c8b733	XAUUSDT	binance	5307.64	5307.65	5307.645	2026-03-01 15:06:26.736906
55c8e574-bce3-4bb0-9a0e-d5a314c420c0	XAUUSDT	binance	5307.6	5307.61	5307.605	2026-03-01 15:06:31.747747
fdca956b-dc42-41d7-a86f-be35eb9db579	XAUUSDT	binance	5307.6	5307.61	5307.605	2026-03-01 15:06:36.750124
de15d219-1fe9-457c-8172-ae2e41426c0a	XAUUSDT	binance	5307.6	5307.61	5307.605	2026-03-01 15:06:41.751694
88e68c20-333b-40a9-85b4-77689ddf19b4	XAUUSDT	binance	5307.6	5307.61	5307.605	2026-03-01 15:06:46.756564
1fdea62c-3587-4855-9b96-e80895048367	XAUUSDT	binance	5307.6	5307.61	5307.605	2026-03-01 15:06:51.762756
2373ee03-e1fd-4248-a1dc-0fab19c8eb32	XAUUSDT	binance	5307.64	5307.65	5307.645	2026-03-01 15:06:56.757844
265a5032-5062-4cda-b848-68329a0ab6e6	XAUUSDT	binance	5307.8	5307.81	5307.805	2026-03-01 15:07:01.771241
3bb09e94-593d-4d2f-b163-09e16a0857c4	XAUUSDT	binance	5307.72	5307.73	5307.725	2026-03-01 15:05:52.815257
53df4e32-33dd-4c48-afe6-0a0ce2005608	XAUUSDT	binance	5307.84	5307.85	5307.845	2026-03-01 15:05:57.80403
1b425c7f-d6ee-4b9f-b834-e2e88e15793f	XAUUSDT	binance	5307.97	5307.98	5307.975	2026-03-01 15:06:02.80946
408f5a3a-52ee-4cb4-a93e-18700d1e63bb	XAUUSDT	binance	5307.97	5307.98	5307.975	2026-03-01 15:06:07.829269
f552e307-f872-44ce-9c86-47d2b132e988	XAUUSDT	binance	5307.97	5307.98	5307.975	2026-03-01 15:06:12.838364
75d2cf87-756a-4d24-9bd4-d5a1a62baccf	XAUUSDT	binance	5307.84	5307.85	5307.845	2026-03-01 15:06:17.829702
8a351495-1775-4d9c-a5d5-d6f8ae068e7d	XAUUSDT	binance	5307.64	5307.65	5307.645	2026-03-01 15:06:22.837568
d22a262a-e66e-4448-83bc-57ae13654cc2	XAUUSDT	binance	5307.64	5307.65	5307.645	2026-03-01 15:06:27.848023
456a69c5-2265-4e79-a385-a80b1a8382a2	XAUUSDT	binance	5307.6	5307.61	5307.605	2026-03-01 15:06:32.818498
b7877cef-7b25-4768-8314-af9755a7d2fd	XAUUSDT	binance	5307.6	5307.61	5307.605	2026-03-01 15:06:37.825331
c9d1f4a1-c353-4166-b03f-553df6171945	XAUUSDT	binance	5307.6	5307.61	5307.605	2026-03-01 15:06:42.835787
e9d28ac3-71cd-451f-853a-ce0ce686875a	XAUUSDT	binance	5307.6	5307.61	5307.605	2026-03-01 15:06:47.822874
f9c2f3ef-7dd2-4d2a-8a9e-ea746cd795d9	XAUUSDT	binance	5307.6	5307.61	5307.605	2026-03-01 15:06:52.830727
9e4db947-f464-4aad-9ad6-9655d1fccc91	XAUUSDT	binance	5307.64	5307.65	5307.645	2026-03-01 15:06:57.842096
ab0308ae-46ba-4d6d-96c4-1cb11f304a3c	XAUUSDT	binance	5307.72	5307.73	5307.725	2026-03-01 15:05:53.584013
58d9519b-d953-46f1-b56f-de31d2e397a3	XAUUSDT	binance	5307.84	5307.85	5307.845	2026-03-01 15:05:58.58927
4f0ea016-aa40-4bbc-95a8-c09888e2bb04	XAUUSDT	binance	5307.97	5307.98	5307.975	2026-03-01 15:06:03.58261
8c7ab3de-d872-4639-8ce3-9b28f5289d07	XAUUSDT	binance	5307.97	5307.98	5307.975	2026-03-01 15:06:08.571729
9a5b32b2-8eab-4224-a9e1-ce237719716e	XAUUSDT	binance	5307.97	5307.98	5307.975	2026-03-01 15:06:13.595409
76b7603c-32da-4adb-95ce-d94ee77404b6	XAUUSDT	binance	5307.84	5307.85	5307.845	2026-03-01 15:06:18.569992
b0f1c1d8-e7df-4286-9579-1f9374a47fcb	XAUUSDT	binance	5307.64	5307.65	5307.645	2026-03-01 15:06:23.58469
271fa5bc-09f3-4119-a733-6b2222bea4c0	XAUUSDT	binance	5307.64	5307.65	5307.645	2026-03-01 15:06:28.593486
a82569b0-93ad-4b6f-afe9-11f6300ed514	XAUUSDT	binance	5307.6	5307.61	5307.605	2026-03-01 15:06:33.595654
eaebca3e-fb70-44a3-bd41-8a96d7441998	XAUUSDT	binance	5307.6	5307.61	5307.605	2026-03-01 15:06:38.599312
127d7a56-a287-403b-9fd6-80549d14517a	XAUUSDT	binance	5307.6	5307.61	5307.605	2026-03-01 15:06:43.588193
014b29a8-8179-42d8-a0a5-4aab9936d4e0	XAUUSDT	binance	5307.6	5307.61	5307.605	2026-03-01 15:06:48.607059
283c8d2b-267f-4819-a17e-aed286301f5d	XAUUSDT	binance	5307.64	5307.65	5307.645	2026-03-01 15:06:53.604118
a8772028-d392-400e-ab12-0efa47e5f82f	XAUUSDT	binance	5307.64	5307.65	5307.645	2026-03-01 15:06:58.613731
afbb86fc-5e3e-4249-8cde-a86b747985f4	XAUUSDT	binance	5307.8	5307.81	5307.805	2026-03-01 15:07:02.829678
5fe64013-702d-4512-a084-96df220337c6	XAUUSDT	binance	5307.8	5307.81	5307.805	2026-03-01 15:07:03.610703
2f9a9cfb-8db9-4202-81f0-263dc2b345b9	XAUUSDT	binance	5307.8	5307.81	5307.805	2026-03-01 15:07:03.830329
374bbccf-9d5c-485b-a233-db4574cd5d4d	XAUUSDT	binance	5307.8	5307.81	5307.805	2026-03-01 15:07:06.785306
51f05449-6bda-4fd9-b188-1da5b0b8769e	XAUUSDT	binance	5307.8	5307.81	5307.805	2026-03-01 15:07:07.844216
4a24406d-f972-4ec8-bca5-c8d7bea43517	XAUUSDT	binance	5307.8	5307.81	5307.805	2026-03-01 15:07:08.611536
a67dd960-697f-4a1f-bb37-ef17843b08a4	XAUUSDT	binance	5307.8	5307.81	5307.805	2026-03-01 15:07:08.83382
b8ae783c-5dfe-464f-978d-bc289487586e	XAUUSDT	binance	5307.8	5307.81	5307.805	2026-03-01 15:07:11.791425
28269a44-bcc7-4049-a8b3-6fc8147d51ea	XAUUSDT	binance	5307.8	5307.81	5307.805	2026-03-01 15:07:12.846585
f848752d-58f4-4b48-a8a6-308eb95261e9	XAUUSDT	binance	5307.8	5307.81	5307.805	2026-03-01 15:07:13.603388
cf920b52-f385-44ac-a656-49bae5ed50a5	XAUUSDT	binance	5307.8	5307.81	5307.805	2026-03-01 15:07:13.839563
ed184c15-f37c-4271-9c68-2d06522ef245	XAUUSDT	binance	5307.8	5307.81	5307.805	2026-03-01 15:07:16.802395
88093acc-8236-4c81-b553-66a8b9deeba5	XAUUSDT	binance	5307.8	5307.81	5307.805	2026-03-01 15:07:17.830244
56c2522a-8aed-44c5-ba57-d2848088dac0	XAUUSDT	binance	5307.8	5307.81	5307.805	2026-03-01 15:07:18.615656
77e396c2-1805-4aeb-985f-3e3b9407feca	XAUUSDT	binance	5307.8	5307.81	5307.805	2026-03-01 15:07:18.848536
a3865c53-eb56-4a72-ade9-d0c56289206f	XAUUSDT	binance	5307.55	5307.56	5307.555	2026-03-01 15:07:21.791886
e8a6cbb6-37a7-4da9-9cab-8addc902350a	XAUUSDT	binance	5307.55	5307.56	5307.555	2026-03-01 15:07:22.824999
dd50febc-0b52-4fec-a5fd-c23435b146bc	XAUUSDT	binance	5307.55	5307.56	5307.555	2026-03-01 15:07:23.623128
43e8a301-0837-442f-a5ec-f45f670d1283	XAUUSDT	binance	5307.55	5307.56	5307.555	2026-03-01 15:07:23.843589
3e4393c9-eb2d-4de5-a5ed-101257daa83a	XAUUSDT	binance	5307.55	5307.56	5307.555	2026-03-01 15:07:26.797979
23e437dd-90b7-4348-9c9e-4f14f514b9b9	XAUUSDT	binance	5307.55	5307.56	5307.555	2026-03-01 15:07:27.829643
713ce22d-5ed9-4e83-8740-a5f1ab47ab2c	XAUUSDT	binance	5307.55	5307.56	5307.555	2026-03-01 15:07:28.623731
1a6270e3-fb56-46b5-b00f-f2683d8d56c4	XAUUSDT	binance	5307.55	5307.56	5307.555	2026-03-01 15:07:28.840446
b5a96c5b-213b-422b-b0d6-9faceff297a2	XAUUSDT	binance	5307.55	5307.56	5307.555	2026-03-01 15:07:31.791087
f3201fb3-8b46-4c64-8673-c99b09a71e7b	XAUUSDT	binance	5307.55	5307.56	5307.555	2026-03-01 15:07:32.83957
27b239dd-d973-4b38-9b67-e6fffbf25d8e	XAUUSDT	binance	5307.55	5307.56	5307.555	2026-03-01 15:07:33.62963
ff1d3d6a-c76e-494b-a3bf-ee52c6090456	XAUUSDT	binance	5307.55	5307.56	5307.555	2026-03-01 15:07:33.837073
ad0b7197-2556-4fd5-803e-1b42aaf92531	XAUUSDT	binance	5307.55	5307.56	5307.555	2026-03-01 15:07:36.798175
3e73c8d9-fa1e-44fc-8daa-148ed035e338	XAUUSDT	binance	5307.55	5307.56	5307.555	2026-03-01 15:07:37.818253
bf8cbf20-956b-412e-b3c7-77428bcd3455	XAUUSDT	binance	5307.55	5307.56	5307.555	2026-03-01 15:07:38.610591
50198204-6415-4219-9e59-f0f51ffd1b48	XAUUSDT	binance	5307.55	5307.56	5307.555	2026-03-01 15:07:38.847735
61bfc44c-91a3-4fd6-b87b-c6117ece4c39	XAUUSDT	binance	5307.55	5307.56	5307.555	2026-03-01 15:07:41.798276
19c5132d-1a3c-49be-98f3-e5e473a9bc9c	XAUUSDT	binance	5307.55	5307.56	5307.555	2026-03-01 15:07:42.835395
8ab8fae3-e3f4-4efb-9a00-5b9b6ce5148d	XAUUSDT	binance	5307.55	5307.56	5307.555	2026-03-01 15:07:43.622284
73f4f212-c03d-4edb-8371-20781a14cea9	XAUUSDT	binance	5307.55	5307.56	5307.555	2026-03-01 15:07:43.845753
d3d9269a-e26c-421b-89f3-bb1b5c41b6e1	XAUUSDT	binance	5307.55	5307.56	5307.555	2026-03-01 15:07:46.798118
c176690f-eed5-45b1-b8de-8b607ae2843e	XAUUSDT	binance	5307.55	5307.56	5307.555	2026-03-01 15:07:47.844315
8a857805-3340-4e30-a904-a8464a773fee	XAUUSDT	binance	5307.55	5307.56	5307.555	2026-03-01 15:07:48.614724
774020a1-141c-4f59-b448-0dfe58b45660	XAUUSDT	binance	5307.55	5307.56	5307.555	2026-03-01 15:07:48.82881
0659d317-1584-4ef2-9e5c-0ec4cba362a5	XAUUSDT	binance	5307.55	5307.56	5307.555	2026-03-01 15:07:51.818537
58cbf47e-33e5-4638-b9d8-c742a370de94	XAUUSDT	binance	5307.55	5307.56	5307.555	2026-03-01 15:07:52.848831
bf21f83f-6844-4e6a-bbad-4eee9d006de6	XAUUSDT	binance	5307.55	5307.56	5307.555	2026-03-01 15:07:53.635631
f046adf2-9c24-4557-b3df-898d926a87bc	XAUUSDT	binance	5307.55	5307.56	5307.555	2026-03-01 15:07:53.825774
62462b5f-cfbd-437a-8373-ea28f1f52a05	XAUUSDT	binance	5307.55	5307.56	5307.555	2026-03-01 15:07:56.823384
309a123d-cf7e-4aad-b922-c6bf97dbe172	XAUUSDT	binance	5307.55	5307.56	5307.555	2026-03-01 15:07:57.84539
a742bad5-6cf8-4d85-9696-5fc18aa5c999	XAUUSDT	binance	5307.55	5307.56	5307.555	2026-03-01 15:07:58.632315
f84799a9-56f7-406b-b06a-9b57df0d42b4	XAUUSDT	binance	5307.55	5307.56	5307.555	2026-03-01 15:07:58.826679
03ebb33c-0871-4871-8f76-c757aff340c4	XAUUSDT	binance	5307.48	5307.49	5307.485	2026-03-01 15:08:01.829576
883944ab-2ca0-49c0-86a3-35efba119566	XAUUSDT	binance	5307.48	5307.49	5307.485	2026-03-01 15:08:02.840988
9e0b475a-3684-4e4b-82b6-ca26d9106e77	XAUUSDT	binance	5307.48	5307.49	5307.485	2026-03-01 15:08:03.636267
387bdc8d-7456-4f75-83af-695298faf112	XAUUSDT	binance	5307.48	5307.49	5307.485	2026-03-01 15:08:03.823906
d945e36a-8943-4349-a448-3f2d6801e27b	XAUUSDT	binance	5307.14	5307.15	5307.145	2026-03-01 15:08:06.822239
69b98f81-b9ee-437f-8a02-8ba81b7f1def	XAUUSDT	binance	5306.34	5306.35	5306.345	2026-03-01 15:08:07.849444
b3eff335-cdac-44a0-b9ae-392d71e0c6ef	XAUUSDT	binance	5306.34	5306.35	5306.345	2026-03-01 15:08:08.654608
8b704281-5fc9-470c-8439-037dd2dce7d1	XAUUSDT	binance	5306.34	5306.35	5306.345	2026-03-01 15:08:08.82942
abc5d2e4-488e-48c6-97d6-abcd3e8b57ba	XAUUSDT	binance	5306.34	5306.35	5306.345	2026-03-01 15:08:11.840402
7a290b61-e109-4d2b-8ac3-c85be45648a0	XAUUSDT	binance	5306.34	5306.35	5306.345	2026-03-01 15:08:12.854618
2eb15a2c-6750-425c-a4b0-49749b666272	XAUUSDT	binance	5306.3	5306.31	5306.305	2026-03-01 15:08:13.658335
d151aba9-b7bb-4b30-96e4-952546d8934f	XAUUSDT	binance	5306.3	5306.31	5306.305	2026-03-01 15:08:13.845296
db077538-edfe-4cd4-8339-e757efc64e2c	XAUUSDT	binance	5306.52	5306.53	5306.525	2026-03-01 15:08:16.853063
63de94dd-98d8-40f8-a76c-7fae6c33b4ec	XAUUSDT	binance	5306.52	5306.53	5306.525	2026-03-01 15:08:17.862672
2c2520c3-607d-4620-a625-a916422f1247	XAUUSDT	binance	5306.52	5306.53	5306.525	2026-03-01 15:08:18.653519
fc7763f0-c790-428d-98c3-073ca93f595a	XAUUSDT	binance	5306.52	5306.53	5306.525	2026-03-01 15:08:18.845437
316e6c2d-c618-4081-8e3f-1490ea46c0d7	XAUUSDT	binance	5306.52	5306.53	5306.525	2026-03-01 15:08:21.860677
a9eba0bc-73b1-449e-a321-ecd7229fa030	XAUUSDT	binance	5306.52	5306.53	5306.525	2026-03-01 15:08:22.854913
ca817330-76fb-4ca7-9fd4-21ceb680f7bf	XAUUSDT	binance	5306.52	5306.53	5306.525	2026-03-01 15:08:23.647764
42bcbe13-457e-4d26-af7b-62c3763e3ba0	XAUUSDT	binance	5306.52	5306.53	5306.525	2026-03-01 15:08:23.830144
1e190ee6-c6e4-4369-bd66-170ce87c4380	XAUUSDT	binance	5306.52	5306.53	5306.525	2026-03-01 15:08:26.874363
f937985b-d3ea-411e-9b4f-36a7623036bb	XAUUSDT	binance	5306.52	5306.53	5306.525	2026-03-01 15:08:27.85422
ad279cb4-fc09-4e47-bbf0-59ca212ea6e0	XAUUSDT	binance	5306.52	5306.53	5306.525	2026-03-01 15:08:28.661003
47fd4aae-558b-45fd-9edd-28ea2966336e	XAUUSDT	binance	5306.52	5306.53	5306.525	2026-03-01 15:08:28.8203
b0f7c655-cf4c-442d-a26f-f0a961deebaa	XAUUSDT	binance	5306.55	5306.56	5306.555	2026-03-01 15:08:31.868364
dc072f89-b797-400c-9e48-c78555c234df	XAUUSDT	binance	5306.54	5306.55	5306.545	2026-03-01 15:08:32.860439
ac53f8f0-766b-4fd7-8945-f9daf7e9a7b4	XAUUSDT	binance	5306.54	5306.55	5306.545	2026-03-01 15:08:33.657318
88450cf9-cfa8-491d-bd34-60972c2b06f0	XAUUSDT	binance	5306.54	5306.55	5306.545	2026-03-01 15:08:33.831445
e9144bb7-8816-43ca-ac06-84bf2be574a5	XAUUSDT	binance	5306.54	5306.55	5306.545	2026-03-01 15:08:38.827807
5c1f9172-cc95-467f-afe7-30578a40eebc	XAUUSDT	binance	5306.54	5306.55	5306.545	2026-03-01 15:08:43.821393
24f74a13-d3a5-4326-a77c-aa2807a879b7	XAUUSDT	binance	5306.54	5306.55	5306.545	2026-03-01 15:08:48.830407
75d5fb1f-8591-4f7c-97b0-9b594f3e1ab2	XAUUSDT	binance	5306.54	5306.55	5306.545	2026-03-01 15:08:53.848213
c2a2f63e-8566-421a-b3b1-f0cbbd5c116c	XAUUSDT	binance	5306.54	5306.55	5306.545	2026-03-01 15:08:58.867518
d765e7e8-5aac-4d3b-a442-903cdb1d5db0	XAUUSDT	binance	5306.54	5306.55	5306.545	2026-03-01 15:09:03.876787
362fb724-ffe8-4776-b11b-9b8b8df2bea2	XAUUSDT	binance	5307.37	5307.38	5307.375	2026-03-01 15:09:08.886012
afb0afe6-4537-488b-b11b-7852d177eeec	XAUUSDT	binance	5307.37	5307.38	5307.375	2026-03-01 15:09:13.882607
cdca335a-db86-4e2f-81e0-514cf5547a64	XAUUSDT	binance	5307.37	5307.38	5307.375	2026-03-01 15:09:18.907601
ad155fe9-ad8d-4823-ac09-df49051f6f2c	XAUUSDT	binance	5307.25	5307.26	5307.255	2026-03-01 15:09:23.900334
26c7d226-92f4-4849-a468-d7631c4f5dcf	XAUUSDT	binance	5307.25	5307.26	5307.255	2026-03-01 15:09:28.926678
7d1a32c1-882a-404c-b9e7-dad6ad1f5480	XAUUSDT	binance	5307.25	5307.26	5307.255	2026-03-01 15:09:33.919832
a32a807b-4ed8-4821-9122-1c6dcecab7e0	XAUUSDT	binance	5307.25	5307.26	5307.255	2026-03-01 15:09:38.92627
9788d2de-634a-43be-a5ba-7ca4ba7e4e5d	XAUUSDT	binance	5307.25	5307.26	5307.255	2026-03-01 15:09:43.907919
80e80d04-e623-4cab-9e06-2614c8ba5147	XAUUSDT	binance	5307.25	5307.26	5307.255	2026-03-01 15:09:48.900531
123cbcc4-e3e2-412b-9e61-6b17834d239e	XAUUSDT	binance	5307.25	5307.26	5307.255	2026-03-01 15:09:53.897465
98e89642-a3f4-4ca9-9470-2464f842acae	XAUUSDT	binance	5307.25	5307.26	5307.255	2026-03-01 15:09:58.921249
4ec3a28a-7dee-444e-bd71-49b19ef06761	XAUUSDT	binance	5306.54	5306.55	5306.545	2026-03-01 15:08:36.872207
1ce28bb0-bc4f-4358-8238-61e9e80e057b	XAUUSDT	binance	5306.54	5306.55	5306.545	2026-03-01 15:08:41.866107
7d4d2c32-290b-4049-97df-71f1873e57bd	XAUUSDT	binance	5306.54	5306.55	5306.545	2026-03-01 15:08:46.875928
aa76a747-340f-4846-99e6-9acc883d9bad	XAUUSDT	binance	5306.54	5306.55	5306.545	2026-03-01 15:08:51.869945
4c07ea2d-e2ab-4ae1-8935-9aa15095db2c	XAUUSDT	binance	5306.54	5306.55	5306.545	2026-03-01 15:08:56.881078
7a161fee-48a6-4bdb-ad0d-b420d40ceab9	XAUUSDT	binance	5306.54	5306.55	5306.545	2026-03-01 15:09:01.890012
53133a67-fbfc-4c77-b959-e4862543585e	XAUUSDT	binance	5306.54	5306.55	5306.545	2026-03-01 15:09:06.883625
c95daf0c-59cc-433d-9a0e-75db88132fff	XAUUSDT	binance	5307.37	5307.38	5307.375	2026-03-01 15:09:11.881553
78e21154-60a6-4a83-b5c0-7c6636c0bde3	XAUUSDT	binance	5307.37	5307.38	5307.375	2026-03-01 15:09:16.891973
6a01fd86-c2c0-4e4f-b9b1-f0bb48ce28b0	XAUUSDT	binance	5307.3	5307.31	5307.305	2026-03-01 15:09:21.885708
8e51859d-13fd-415b-9ee7-b010f639eaf9	XAUUSDT	binance	5307.25	5307.26	5307.255	2026-03-01 15:09:26.895193
e1f70420-d8a1-478d-b3bf-47d657b048f0	XAUUSDT	binance	5307.25	5307.26	5307.255	2026-03-01 15:09:31.903915
6f7fffd9-849a-449e-bf72-44a156b80d44	XAUUSDT	binance	5307.25	5307.26	5307.255	2026-03-01 15:09:36.927253
5da9c527-9660-4ea0-9816-c2a408811895	XAUUSDT	binance	5307.25	5307.26	5307.255	2026-03-01 15:09:41.919425
0b5d9c52-561c-407f-af2b-f215cd763178	XAUUSDT	binance	5307.25	5307.26	5307.255	2026-03-01 15:09:46.91652
f887a746-df6a-4912-a2ca-9b31f46bc3cc	XAUUSDT	binance	5307.25	5307.26	5307.255	2026-03-01 15:09:51.909811
7a83dbf7-30f0-4cfe-b701-bda2e3d6fbe4	XAUUSDT	binance	5307.25	5307.26	5307.255	2026-03-01 15:09:56.919889
8d5ff05a-f550-43e9-bae7-8c4cf711ab23	XAUUSDT	binance	5307.25	5307.26	5307.255	2026-03-01 15:10:01.913566
5a78dfd4-7166-4a90-9827-aaf72752bfe1	XAUUSDT	binance	5306.54	5306.55	5306.545	2026-03-01 15:08:37.866865
9b36ebb7-65e9-4de4-893a-6ce02e892960	XAUUSDT	binance	5306.54	5306.55	5306.545	2026-03-01 15:08:42.875675
d340e180-aeaf-4333-9997-df945bd32db0	XAUUSDT	binance	5306.54	5306.55	5306.545	2026-03-01 15:08:47.852407
25023f60-5e42-4d4c-90ee-6d94bc368a9a	XAUUSDT	binance	5306.54	5306.55	5306.545	2026-03-01 15:08:52.87962
3b29293e-aba2-4d28-aa80-3116bd2c0091	XAUUSDT	binance	5306.54	5306.55	5306.545	2026-03-01 15:08:57.883077
ade9d683-84c0-41b3-842e-cb80b4b1307a	XAUUSDT	binance	5306.54	5306.55	5306.545	2026-03-01 15:09:02.882716
ed95feb9-f682-4cb0-b328-49168110a944	XAUUSDT	binance	5307.37	5307.38	5307.375	2026-03-01 15:09:07.893694
2dba8df1-14ee-4bd0-bc64-a72b9d24de90	XAUUSDT	binance	5307.37	5307.38	5307.375	2026-03-01 15:09:12.888296
f2867884-1cb9-4512-9c71-af83d20aba52	XAUUSDT	binance	5307.37	5307.38	5307.375	2026-03-01 15:09:17.882159
1d438395-c2f4-4f13-8aae-5fb5952fc4a9	XAUUSDT	binance	5307.3	5307.31	5307.305	2026-03-01 15:09:22.891936
1c259440-ba79-4526-8f4f-80b6eba45c69	XAUUSDT	binance	5307.25	5307.26	5307.255	2026-03-01 15:09:27.902072
597314d4-772a-4624-bc90-b2fa06fd36dc	XAUUSDT	binance	5307.25	5307.26	5307.255	2026-03-01 15:09:32.896707
83dd7244-1954-4cd0-94a6-7ad72c3a9dfd	XAUUSDT	binance	5307.25	5307.26	5307.255	2026-03-01 15:09:37.910971
d47573b4-9538-4c65-839f-ce98446af253	XAUUSDT	binance	5307.25	5307.26	5307.255	2026-03-01 15:09:42.9131
76abafc6-0164-490c-b055-47eb72d30e11	XAUUSDT	binance	5307.25	5307.26	5307.255	2026-03-01 15:09:47.924194
1790ffeb-8e40-48ae-b9fa-00de28b57b0e	XAUUSDT	binance	5307.25	5307.26	5307.255	2026-03-01 15:09:52.919871
c506ece6-b398-493f-a942-02cfb5044a5b	XAUUSDT	binance	5307.25	5307.26	5307.255	2026-03-01 15:09:57.927359
63abab48-656c-4d5a-b439-504a12f887e2	XAUUSDT	binance	5306.54	5306.55	5306.545	2026-03-01 15:08:38.653943
c8bad26e-7c19-4c53-afb3-b73d014cac62	XAUUSDT	binance	5306.54	5306.55	5306.545	2026-03-01 15:08:43.663682
75c0c158-ab4f-4b58-839e-1220448fe4cf	XAUUSDT	binance	5306.54	5306.55	5306.545	2026-03-01 15:08:48.672888
37ac63a8-c9cc-4a19-8c39-1b3767cd2c6c	XAUUSDT	binance	5306.54	5306.55	5306.545	2026-03-01 15:08:53.668287
96cda3b9-65d1-4853-99a6-22dbd0b4487e	XAUUSDT	binance	5306.54	5306.55	5306.545	2026-03-01 15:08:58.647227
aa53615a-141d-4971-a30d-192c6e303725	XAUUSDT	binance	5306.54	5306.55	5306.545	2026-03-01 15:09:03.671648
f00b51d0-771c-40a1-94c3-eea739f3c8a7	XAUUSDT	binance	5307.37	5307.38	5307.375	2026-03-01 15:09:08.665292
66240485-99a7-472b-95f4-a7300321a64d	XAUUSDT	binance	5307.37	5307.38	5307.375	2026-03-01 15:09:13.67743
589d73ae-e6ac-485a-b648-fb16ce64a2d5	XAUUSDT	binance	5307.37	5307.38	5307.375	2026-03-01 15:09:18.703558
cdeb9c68-bed6-411b-bcb2-eef8f30f460c	XAUUSDT	binance	5307.25	5307.26	5307.255	2026-03-01 15:09:23.7109
bcbc535a-e1f8-4761-865f-63443a0e68c2	XAUUSDT	binance	5307.25	5307.26	5307.255	2026-03-01 15:09:28.705891
7b7def8d-7c87-4a07-b544-f8dcff1611ff	XAUUSDT	binance	5307.25	5307.26	5307.255	2026-03-01 15:09:33.699628
f275c3d0-5c79-42fc-b1fe-18cbc82cc753	XAUUSDT	binance	5307.25	5307.26	5307.255	2026-03-01 15:09:38.705612
dce74d6b-70bb-4838-8e9a-c6b4219cc0a6	XAUUSDT	binance	5307.25	5307.26	5307.255	2026-03-01 15:09:43.716859
bf7cd68c-8a69-4f82-b0a9-f132112326e1	XAUUSDT	binance	5307.25	5307.26	5307.255	2026-03-01 15:09:48.711125
dd497fb1-59a4-4524-a747-be24597bb819	XAUUSDT	binance	5307.25	5307.26	5307.255	2026-03-01 15:09:53.724115
f9f38b13-4cb6-4b7d-954f-74c952f3afd1	XAUUSDT	binance	5307.25	5307.26	5307.255	2026-03-01 15:09:58.716068
8a577c6f-afd5-435d-8efe-ae3d0b6a38ce	XAUUSDT	binance	5307.25	5307.26	5307.255	2026-03-01 15:10:02.921898
cde45a3e-69b0-468d-b887-73809caac6e3	XAUUSDT	binance	5307.25	5307.26	5307.255	2026-03-01 15:10:03.709594
96c6985a-4c69-462d-8fab-b4d5c4aa0a06	XAUUSDT	binance	5307.25	5307.26	5307.255	2026-03-01 15:10:03.914746
82468988-0d9c-4ab7-a6c5-c3b2c530d5cc	XAUUSDT	binance	5307.08	5307.09	5307.085	2026-03-01 15:10:06.92449
2a85d95e-af1d-47db-ad35-1fce8e01d196	XAUUSDT	binance	5307.08	5307.09	5307.085	2026-03-01 15:10:07.916229
17297721-f609-4ff7-8a0a-acf5b65eaf6d	XAUUSDT	binance	5306.83	5306.84	5306.835	2026-03-01 15:10:08.703181
76597a72-c9fd-4655-b448-90085aad65c6	XAUUSDT	binance	5306.83	5306.84	5306.835	2026-03-01 15:10:08.923868
7ad32ef6-371a-461f-b141-3d1a056f22f7	XAUUSDT	binance	5306.34	5306.35	5306.345	2026-03-01 15:10:11.917809
cec62691-9922-44bf-9d92-e459038a172c	XAUUSDT	binance	5306.34	5306.35	5306.345	2026-03-01 15:10:12.909722
b2a0131c-b155-4e53-85c9-64f258af5564	XAUUSDT	binance	5306.34	5306.35	5306.345	2026-03-01 15:10:13.696817
a34c33f0-1e5b-4020-a03c-c00d36fa00b3	XAUUSDT	binance	5306.34	5306.35	5306.345	2026-03-01 15:10:13.91746
ab1a14d1-01f3-4805-9381-8681f48847cc	XAUUSDT	binance	5306.34	5306.35	5306.345	2026-03-01 15:10:16.911672
4398f398-7ce4-4d55-b059-9eb98bf7f461	XAUUSDT	binance	5306.34	5306.35	5306.345	2026-03-01 15:10:17.913023
27386b1b-fa00-4a89-a3cc-f9b6ec702566	XAUUSDT	binance	5306.21	5306.22	5306.215	2026-03-01 15:10:18.707076
1d16e9e8-cb99-42ee-9911-5b02aa05883d	XAUUSDT	binance	5306.21	5306.22	5306.215	2026-03-01 15:10:18.914522
5c6b7109-4fb8-40a2-8768-24768a37eb37	XAUUSDT	binance	5305.67	5305.68	5305.675	2026-03-01 15:10:21.898064
f1475db0-9046-4b92-866f-9fb072f82c78	XAUUSDT	binance	5305.67	5305.68	5305.675	2026-03-01 15:10:22.925895
42d91db1-561a-4061-a86a-386b1361656e	XAUUSDT	binance	5305.67	5305.68	5305.675	2026-03-01 15:10:23.693959
452a44f2-712c-4768-842d-66c0d637c4be	XAUUSDT	binance	5305.67	5305.68	5305.675	2026-03-01 15:10:23.916938
197fdf1d-6cde-412c-a230-e6ae23037ee3	XAUUSDT	binance	5305.67	5305.68	5305.675	2026-03-01 15:10:26.90071
cf69a636-a345-4dc5-b251-4934f2507621	XAUUSDT	binance	5305.67	5305.68	5305.675	2026-03-01 15:10:27.918253
002932b7-7732-4a7e-a7cb-ce6f838324c5	XAUUSDT	binance	5305.67	5305.68	5305.675	2026-03-01 15:10:28.712618
ecc91ce4-e077-4113-93a9-47460a7aadc6	XAUUSDT	binance	5305.67	5305.68	5305.675	2026-03-01 15:10:28.919348
4e47a7cc-a54d-44ea-9981-ae0cf51e8639	XAUUSDT	binance	5305.67	5305.68	5305.675	2026-03-01 15:10:31.902993
f1afed44-f51e-42ec-8eca-dddd902493e7	XAUUSDT	binance	5305.67	5305.68	5305.675	2026-03-01 15:10:32.920535
e8be6393-2b30-48f4-8cad-0c7b375a91cc	XAUUSDT	binance	5305.67	5305.68	5305.675	2026-03-01 15:10:33.715033
496212f9-a33b-458d-9387-c98497f97c45	XAUUSDT	binance	5305.67	5305.68	5305.675	2026-03-01 15:10:33.924917
1ebf799d-3e58-404c-a988-5e3757a46cd4	XAUUSDT	binance	5305.25	5305.26	5305.255	2026-03-01 15:10:36.906304
c5409678-b384-41c5-a56f-b38acd15f75f	XAUUSDT	binance	5305.25	5305.26	5305.255	2026-03-01 15:10:37.923832
cfbf5b5d-c124-484a-b94a-62c17675a206	XAUUSDT	binance	5305.25	5305.26	5305.255	2026-03-01 15:10:38.702296
81314bf4-7e39-4fca-bff5-867626bb786a	XAUUSDT	binance	5305.25	5305.26	5305.255	2026-03-01 15:10:38.90868
da5942f6-856b-4c22-ad8c-ef56d837e8d0	XAUUSDT	binance	5305.25	5305.26	5305.255	2026-03-01 15:10:41.911487
68b3395b-c387-4ea0-9d39-5745a1a0fda1	XAUUSDT	binance	5305.25	5305.26	5305.255	2026-03-01 15:10:42.926344
0be9a2c2-13dc-4bff-82c8-e3ea148a515a	XAUUSDT	binance	5305.25	5305.26	5305.255	2026-03-01 15:10:43.705164
3569c74f-8924-44fe-8808-f61243531400	XAUUSDT	binance	5305.25	5305.26	5305.255	2026-03-01 15:10:43.912068
151292c5-f18c-45f3-85c5-f718553611fd	XAUUSDT	binance	5305.25	5305.26	5305.255	2026-03-01 15:10:46.920611
0b4275e9-a89b-42f2-a64c-232812ca995a	XAUUSDT	binance	5305.25	5305.26	5305.255	2026-03-01 15:10:47.899169
20e6ebcd-5765-4157-826b-4567a14ade63	XAUUSDT	binance	5305.25	5305.26	5305.255	2026-03-01 15:10:48.694421
55db27e0-9015-49f5-9968-2b7b9b52602d	XAUUSDT	binance	5305.25	5305.26	5305.255	2026-03-01 15:10:48.919542
c66ef5c2-e867-4d2e-bc9f-a8520b8a24be	XAUUSDT	binance	5305.25	5305.26	5305.255	2026-03-01 15:10:51.920428
2bca2841-f9d7-4de5-abd9-d41b89e9ca9a	XAUUSDT	binance	5305.25	5305.26	5305.255	2026-03-01 15:10:52.902251
2fe370f8-4bf1-4f2d-b707-f65734abcf22	XAUUSDT	binance	5305.25	5305.26	5305.255	2026-03-01 15:10:53.712563
9126333d-13d0-4143-b4d3-26eb1cc220aa	XAUUSDT	binance	5305.25	5305.26	5305.255	2026-03-01 15:10:53.918999
e1b8e818-6244-49ef-a2d5-2821b21cab8a	XAUUSDT	binance	5305.25	5305.26	5305.255	2026-03-01 15:10:56.907268
dee4060a-4cde-44da-b48f-7337ebcca828	XAUUSDT	binance	5305.25	5305.26	5305.255	2026-03-01 15:10:57.920685
2e9c317b-5361-467a-b313-be2dcb9bfb11	XAUUSDT	binance	5305.25	5305.26	5305.255	2026-03-01 15:10:58.699111
4313df15-4b69-491f-9fb1-9d14c7e3453b	XAUUSDT	binance	5305.25	5305.26	5305.255	2026-03-01 15:10:58.90549
af45040a-3493-4028-bbe2-11ea8bcfe7b9	XAUUSDT	binance	5305.25	5305.26	5305.255	2026-03-01 15:11:01.912041
6ee9820a-fa78-4602-8ac0-2bb06ac431b8	XAUUSDT	binance	5305.25	5305.26	5305.255	2026-03-01 15:11:02.913001
66929b36-4f68-44e1-ad54-a4babd6a38a4	XAUUSDT	binance	5305.25	5305.26	5305.255	2026-03-01 15:11:03.707503
8a603ad2-4183-427a-ae27-039911e2d8f7	XAUUSDT	binance	5305.25	5305.26	5305.255	2026-03-01 15:11:03.910317
bad5d1f0-ce6d-457b-a85b-cfa41618daa6	XAUUSDT	binance	5305.25	5305.26	5305.255	2026-03-01 15:11:06.901443
937c5370-7be3-4d2b-baa3-06c4b290029b	XAUUSDT	binance	5305.25	5305.26	5305.255	2026-03-01 15:11:07.915814
16a590a7-d13b-4774-a436-0d185e9bd86b	XAUUSDT	binance	5305.25	5305.26	5305.255	2026-03-01 15:11:08.730618
3368a435-7912-4f1d-825d-60d8680d8ff0	XAUUSDT	binance	5305.25	5305.26	5305.255	2026-03-01 15:11:08.897068
64ccde1f-b7ec-43ae-aedc-bd4a91b58869	XAUUSDT	binance	5305.25	5305.26	5305.255	2026-03-01 15:11:11.916562
6b56bcd9-c7e7-4ee3-b90e-1f2d04b49a4c	XAUUSDT	binance	5305.25	5305.26	5305.255	2026-03-01 15:11:12.917892
4306ad64-baa9-4aa1-840b-40e0a729081b	XAUUSDT	binance	5305.25	5305.26	5305.255	2026-03-01 15:11:13.725993
3d0d45ed-3f52-453e-8929-6c302d5f3464	XAUUSDT	binance	5305.25	5305.26	5305.255	2026-03-01 15:11:13.9155
2f82d838-a4b3-45d3-9f7e-1ba1ee22125b	XAUUSDT	binance	5305.25	5305.26	5305.255	2026-03-01 15:11:16.919393
43fd713d-dc5c-42f2-97f4-d28289e1560f	XAUUSDT	binance	5305.25	5305.26	5305.255	2026-03-01 15:11:17.920421
ae95e266-4376-4d41-a819-854872518ce6	XAUUSDT	binance	5305.25	5305.26	5305.255	2026-03-01 15:11:18.75443
58609c6f-d368-4534-a889-a0711cd5d1b5	XAUUSDT	binance	5305.25	5305.26	5305.255	2026-03-01 15:11:18.904468
97c0199b-dfff-4571-b7b9-9a21aad6c64f	XAUUSDT	binance	5305.25	5305.26	5305.255	2026-03-01 15:11:21.921029
bbc6c27d-75a2-4c85-8a87-599078af3690	XAUUSDT	binance	5305.25	5305.26	5305.255	2026-03-01 15:11:22.92221
55a4ebbf-a7db-42e3-afe4-2d45f894d3dd	XAUUSDT	binance	5305.25	5305.26	5305.255	2026-03-01 15:11:23.772066
10e79a83-3fbe-49f3-af09-c63489e0b708	XAUUSDT	binance	5305.25	5305.26	5305.255	2026-03-01 15:11:23.92353
86652458-cfda-4932-a6c4-165a55496abe	XAUUSDT	binance	5305.25	5305.26	5305.255	2026-03-01 15:11:26.922792
f749beab-7f33-48a0-8cb8-5e5046fd298a	XAUUSDT	binance	5305.25	5305.26	5305.255	2026-03-01 15:11:27.90863
2c04c60e-9f43-42e3-a47e-3fdce33ca659	XAUUSDT	binance	5305.25	5305.26	5305.255	2026-03-01 15:11:28.777874
12ab35a7-9054-4683-9a4a-ef6643bd0200	XAUUSDT	binance	5305.25	5305.26	5305.255	2026-03-01 15:11:28.903179
517f0648-0cca-4cb8-99b8-dde9204d6063	XAUUSDT	binance	5305.25	5305.26	5305.255	2026-03-01 15:11:31.906642
f51e7dea-ffe3-45d4-a7f4-9efe1bf9d073	XAUUSDT	binance	5305.49	5305.5	5305.495	2026-03-01 15:11:36.927957
c622c962-7f61-42a6-98fd-3e23be2cd145	XAUUSDT	binance	5305.49	5305.5	5305.495	2026-03-01 15:11:41.930531
3151aac3-a48a-45a8-98e6-25a2685fb869	XAUUSDT	binance	5305.49	5305.5	5305.495	2026-03-01 15:11:46.93394
03ddcf65-b100-4358-bf09-1bac2ec8a865	XAUUSDT	binance	5305.25	5305.26	5305.255	2026-03-01 15:11:51.952971
297797d5-88f2-48fd-8fb4-5808c1757fa1	XAUUSDT	binance	5305.49	5305.5	5305.495	2026-03-01 15:11:56.971957
a91bbd2e-fb47-4a55-86c5-9dfd2dfb03f8	XAUUSDT	binance	5305.49	5305.5	5305.495	2026-03-01 15:12:01.956066
ef27cefa-8f55-4335-80d7-6c1f5bcb7fd9	XAUUSDT	binance	5305.99	5306	5305.995	2026-03-01 15:12:06.980369
4ed22599-8466-4b5b-b8ce-f214132e7d8f	XAUUSDT	binance	5306.33	5306.34	5306.335	2026-03-01 15:12:19.049295
245c0c60-620e-4a2d-8f0b-9c26a4e433ec	XAUUSDT	binance	5307	5307.01	5307.005	2026-03-01 15:12:24.034486
90830b48-6579-42e0-a230-0c407ad7f689	XAUUSDT	binance	5307	5307.01	5307.005	2026-03-01 15:12:29.027072
d15ff0f8-f2ec-4806-addf-3302f6aa6781	XAUUSDT	binance	5306.27	5306.28	5306.275	2026-03-01 15:12:34.04255
0b56d71f-a049-4e11-bcea-75a40a26ae37	XAUUSDT	binance	5306.72	5306.73	5306.725	2026-03-01 15:12:45.760835
b96b21ca-7647-476c-b907-0c637340eb1f	XAUUSDT	binance	5306.72	5306.73	5306.725	2026-03-01 15:12:50.765978
fee47297-fd33-4abe-96ed-9ab3187bfa84	XAUUSDT	binance	5307.04	5307.05	5307.045	2026-03-01 15:12:55.756735
dddcc662-20bf-4960-9526-cdf9017f5793	XAUUSDT	binance	5307.19	5307.2	5307.195	2026-03-01 15:13:00.762255
1bca6600-5419-416c-887d-cde80a37d25a	XAUUSDT	binance	5305.25	5305.26	5305.255	2026-03-01 15:11:32.907406
55d75096-5b48-41f6-8ef6-a803c9ffa465	XAUUSDT	binance	5305.49	5305.5	5305.495	2026-03-01 15:11:37.915574
ad6fb9eb-95f8-49a9-a8dc-17978b4ed1ab	XAUUSDT	binance	5305.49	5305.5	5305.495	2026-03-01 15:11:42.915858
83429e3a-bd09-4b89-849c-12bfb8d09805	XAUUSDT	binance	5305.49	5305.5	5305.495	2026-03-01 15:11:47.919441
e138cb47-f849-47fe-a2dd-5f85e096a28f	XAUUSDT	binance	5305.25	5305.26	5305.255	2026-03-01 15:11:52.922875
33d63aea-69ef-460f-8c6e-93317fcd1702	XAUUSDT	binance	5305.49	5305.5	5305.495	2026-03-01 15:11:57.910117
ca6a28ce-c9f8-4860-a652-bea1851e651f	XAUUSDT	binance	5305.49	5305.5	5305.495	2026-03-01 15:12:02.914218
6a18aa5b-31c4-4d4a-a0a6-451e390b75f0	XAUUSDT	binance	5306.33	5306.34	5306.335	2026-03-01 15:12:07.919337
dbb44d13-b293-4670-ae79-41474eb0be2f	XAUUSDT	binance	5306.33	5306.34	5306.335	2026-03-01 15:12:12.927465
79c52238-929d-4c74-8351-db1d79d266fb	XAUUSDT	binance	5306.33	5306.34	5306.335	2026-03-01 15:12:17.935531
eb4c5a5d-87a4-447b-9eee-d5a196f0dbc9	XAUUSDT	binance	5307	5307.01	5307.005	2026-03-01 15:12:22.931779
9454025e-9fa9-4c51-bc8c-ff650a66b0cc	XAUUSDT	binance	5307	5307.01	5307.005	2026-03-01 15:12:27.939806
2e2eff7b-fb33-45e3-8075-090b02f8b708	XAUUSDT	binance	5306.27	5306.28	5306.275	2026-03-01 15:12:32.93933
59843d4c-b194-456e-9f22-05dbfaa1f197	XAUUSDT	binance	5306.72	5306.73	5306.725	2026-03-01 15:12:37.939392
a0ea44ce-2324-4c3b-a7cd-bcd175697eda	XAUUSDT	binance	5306.72	5306.73	5306.725	2026-03-01 15:12:42.939407
06e7d8bd-1f33-4c40-901a-3e73a6d640e3	XAUUSDT	binance	5306.72	5306.73	5306.725	2026-03-01 15:12:47.933523
24bac2c2-aec2-4a4d-b5a4-e0357b44d9b8	XAUUSDT	binance	5306.72	5306.73	5306.725	2026-03-01 15:12:52.940079
c32bfe59-09df-44c3-8956-721b5c6ca255	XAUUSDT	binance	5307.04	5307.05	5307.045	2026-03-01 15:12:57.945472
0fcd156b-5cfe-4a64-b866-e8ac571f52c3	XAUUSDT	binance	5305.25	5305.26	5305.255	2026-03-01 15:11:33.797272
7755a692-bdbc-4aca-a882-caf794b301ae	XAUUSDT	binance	5305.49	5305.5	5305.495	2026-03-01 15:11:38.787158
88ec2aa5-0510-4a2e-a1a1-bf7fd9ef0456	XAUUSDT	binance	5305.49	5305.5	5305.495	2026-03-01 15:11:43.789516
192f0c78-0017-4e2f-ba55-70bffc4783d2	XAUUSDT	binance	5305.25	5305.26	5305.255	2026-03-01 15:11:48.777639
6bb530a1-acd4-49aa-94c6-d3ef826cf8d9	XAUUSDT	binance	5305.25	5305.26	5305.255	2026-03-01 15:11:53.797123
a7ab5355-0fa5-46e2-b375-fd59755a3700	XAUUSDT	binance	5305.49	5305.5	5305.495	2026-03-01 15:11:58.800352
98b2d840-b7aa-4c1b-895c-69eef3fe1d03	XAUUSDT	binance	5305.49	5305.5	5305.495	2026-03-01 15:12:03.789103
1d7c5dc5-88c1-42e3-9214-c28f9d90f258	XAUUSDT	binance	5306.33	5306.34	5306.335	2026-03-01 15:12:08.794397
8c79d2d3-5fe1-402b-a489-489f11a37b8c	XAUUSDT	binance	5306.33	5306.34	5306.335	2026-03-01 15:12:13.79113
a911ba9b-d573-41f2-9da3-48517953ac8b	XAUUSDT	binance	5306.55	5306.56	5306.555	2026-03-01 15:12:18.786416
4f749be5-f0e2-441f-81c4-508059d87273	XAUUSDT	binance	5307	5307.01	5307.005	2026-03-01 15:12:23.78251
184429cb-e354-4b39-aca6-5d375b89f586	XAUUSDT	binance	5307	5307.01	5307.005	2026-03-01 15:12:28.790617
dc9bc0fd-01c4-4cc1-b60c-86012b3d20d8	XAUUSDT	binance	5306.27	5306.28	5306.275	2026-03-01 15:12:33.790562
89bd469e-988f-434d-ac54-8dd4d1bfb459	XAUUSDT	binance	5306.65	5306.66	5306.655	2026-03-01 15:12:38.789631
e3e88c95-b9a9-42f1-9f1a-c761c163be0b	XAUUSDT	binance	5306.72	5306.73	5306.725	2026-03-01 15:12:43.789132
ef2e9ddf-827a-4b4b-9684-51a3d3a9f046	XAUUSDT	binance	5306.72	5306.73	5306.725	2026-03-01 15:12:48.781994
579404a7-c73f-43bf-bc90-37fe3c011090	XAUUSDT	binance	5306.72	5306.73	5306.725	2026-03-01 15:12:53.774307
14753721-1aa5-41fe-95da-b43e8cdc43ef	XAUUSDT	binance	5307.04	5307.05	5307.045	2026-03-01 15:12:58.780425
1db4e99b-afd1-4d12-a80a-04aaecbc89dc	XAUUSDT	binance	5305.25	5305.26	5305.255	2026-03-01 15:11:33.909422
48b23e6e-c656-47cb-99ee-e8f3b694d478	XAUUSDT	binance	5305.49	5305.5	5305.495	2026-03-01 15:11:38.898906
b57cf51c-8cf7-4bbf-a059-be0cbd396e3d	XAUUSDT	binance	5305.49	5305.5	5305.495	2026-03-01 15:11:43.91677
5d453d6b-b9e3-491f-95bf-c11f6dfe06a4	XAUUSDT	binance	5305.25	5305.26	5305.255	2026-03-01 15:11:48.905157
b4d83a23-495f-4cd5-ad7a-3e987bfd2075	XAUUSDT	binance	5305.25	5305.26	5305.255	2026-03-01 15:11:53.908741
7f2b37a9-285b-47cd-88b4-9af3a4e08265	XAUUSDT	binance	5305.49	5305.5	5305.495	2026-03-01 15:11:58.936004
aa7e0648-6a7b-44c6-8b45-70befd8381c2	XAUUSDT	binance	5305.49	5305.5	5305.495	2026-03-01 15:12:03.932529
d8ae9490-e2f3-4333-80e3-7c40fdc379f7	XAUUSDT	binance	5306.33	5306.34	5306.335	2026-03-01 15:12:08.936066
ba05de6e-a43e-434e-8a80-47e8722f086c	XAUUSDT	binance	5306.33	5306.34	5306.335	2026-03-01 15:12:13.94591
212c75cd-b67d-4e85-9adc-c87a3a896618	XAUUSDT	binance	5307	5307.01	5307.005	2026-03-01 15:12:18.960384
e65d4fe6-0465-480d-ac31-25b89c1ded98	XAUUSDT	binance	5307	5307.01	5307.005	2026-03-01 15:12:23.971481
218cc84d-f4ba-4fb5-a2f7-4ac54319f315	XAUUSDT	binance	5307	5307.01	5307.005	2026-03-01 15:12:28.964068
4de0353b-34f8-4b93-be5f-2b10c6f52381	XAUUSDT	binance	5306.27	5306.28	5306.275	2026-03-01 15:12:33.963996
1ef7e333-43ac-4822-a403-11677b01441c	XAUUSDT	binance	5306.65	5306.66	5306.655	2026-03-01 15:12:38.963627
28225dd6-fee0-4028-8e82-af3960b78466	XAUUSDT	binance	5306.72	5306.73	5306.725	2026-03-01 15:12:43.962963
a39f7207-75d0-41e8-bed5-a65261ca1438	XAUUSDT	binance	5306.72	5306.73	5306.725	2026-03-01 15:12:48.97095
c4330603-5b3c-4de2-b2b1-6c63562eab3f	XAUUSDT	binance	5306.72	5306.73	5306.725	2026-03-01 15:12:53.962276
5f8380b8-1ff1-4004-aff2-9d63ca9cfb2a	XAUUSDT	binance	5307.04	5307.05	5307.045	2026-03-01 15:12:58.953333
cdf9ae04-a104-4b96-aa6b-2075db8aa33c	XAUUSDT	binance	5307.19	5307.2	5307.195	2026-03-01 15:13:02.966724
01630c77-ac6b-4043-b481-04b7122ca3fa	XAUUSDT	binance	5307.19	5307.2	5307.195	2026-03-01 15:13:03.785236
0bffaea2-2942-407b-bb24-76dcc768f70e	XAUUSDT	binance	5307.19	5307.2	5307.195	2026-03-01 15:13:03.974116
9a2dcd74-f9d1-4165-a756-f8430f07bd46	XAUUSDT	binance	5307.19	5307.2	5307.195	2026-03-01 15:13:05.767143
ef411a20-a565-4216-ad29-fa1179670333	XAUUSDT	binance	5307.19	5307.2	5307.195	2026-03-01 15:13:07.987401
03787f65-5780-44ef-9e56-d026041c8c22	XAUUSDT	binance	5307.19	5307.2	5307.195	2026-03-01 15:13:08.774757
cb14e7fb-ed8c-4a16-93fb-a6fb98e2f310	XAUUSDT	binance	5307.19	5307.2	5307.195	2026-03-01 15:13:08.979333
f7afc1fd-bf9e-4fb5-9732-139401ee08d5	XAUUSDT	binance	5307.19	5307.2	5307.195	2026-03-01 15:13:10.772083
6f4f4150-4197-48d2-b042-1f91a14af614	XAUUSDT	binance	5307.19	5307.2	5307.195	2026-03-01 15:13:12.992584
e58071e7-6e12-4408-acea-f7fcec2db247	XAUUSDT	binance	5307.19	5307.2	5307.195	2026-03-01 15:13:13.795742
c4b765c3-4539-43fe-9d2c-d8d925ced4ff	XAUUSDT	binance	5307.19	5307.2	5307.195	2026-03-01 15:13:14.000389
2b58bd61-67e7-4901-b40f-993cb45d4f69	XAUUSDT	binance	5307.19	5307.2	5307.195	2026-03-01 15:13:15.777466
1373549f-26fb-4d93-bb18-1d3d732a65f1	XAUUSDT	binance	5307.19	5307.2	5307.195	2026-03-01 15:13:17.998066
95715104-5742-4df5-914c-1ad1315ff052	XAUUSDT	binance	5307.19	5307.2	5307.195	2026-03-01 15:13:18.800916
8b4f913b-95e6-411b-9d15-63f692c8344f	XAUUSDT	binance	5307.19	5307.2	5307.195	2026-03-01 15:13:19.006013
ed481cf1-d8d5-460f-8c53-31a3c79b2f27	XAUUSDT	binance	5307.19	5307.2	5307.195	2026-03-01 15:13:20.782902
75b7e3ef-7e13-4b0d-8178-00ceb3c9bceb	XAUUSDT	binance	5307.19	5307.2	5307.195	2026-03-01 15:13:22.997852
cd48cdfc-19aa-4660-aaf0-3c65fa8befc0	XAUUSDT	binance	5307.19	5307.2	5307.195	2026-03-01 15:13:23.79122
31493457-7884-4ba3-a942-e1d1e6de8e7d	XAUUSDT	binance	5307.19	5307.2	5307.195	2026-03-01 15:13:24.016612
857111d6-a081-4253-8978-93a05315a69a	XAUUSDT	binance	5307.19	5307.2	5307.195	2026-03-01 15:13:25.797747
e9aac83e-475d-4560-8687-3c276449c3c2	XAUUSDT	binance	5307.19	5307.2	5307.195	2026-03-01 15:13:28.002786
3aa55fd2-eef0-4e15-aa1b-1d012204b5e1	XAUUSDT	binance	5307.19	5307.2	5307.195	2026-03-01 15:13:28.798137
8a8e57a6-4c9f-4e21-a72f-8299a9ee9a45	XAUUSDT	binance	5307.19	5307.2	5307.195	2026-03-01 15:13:29.020973
5c62913c-4b6c-4870-a605-54c940ba0341	XAUUSDT	binance	5307.19	5307.2	5307.195	2026-03-01 15:13:30.804315
f2807b22-0c62-4d5c-94e8-b3f5d4e2e199	XAUUSDT	binance	5307.19	5307.2	5307.195	2026-03-01 15:13:32.985564
0060f711-a1ea-4817-bd70-6360ba0b5aa4	XAUUSDT	binance	5307.19	5307.2	5307.195	2026-03-01 15:13:33.777861
23e9d41f-03ea-40b7-912e-af306617fa76	XAUUSDT	binance	5307.19	5307.2	5307.195	2026-03-01 15:13:34.047957
eee8ae1a-7717-4f3b-a7db-2cec8988bdaa	XAUUSDT	binance	5307.19	5307.2	5307.195	2026-03-01 15:13:35.813433
8a7be06f-465b-4159-9957-2de03db810bb	XAUUSDT	binance	5306.86	5306.87	5306.865	2026-03-01 15:13:37.988961
46d69d4a-9ba7-4cad-b134-2ef43b024d3e	XAUUSDT	binance	5306.86	5306.87	5306.865	2026-03-01 15:13:38.782268
45c3002a-fca6-473d-8ed8-dc507c61da4d	XAUUSDT	binance	5306.86	5306.87	5306.865	2026-03-01 15:13:39.052783
e09ff709-3a33-4449-ac93-ad4c2117fcd6	XAUUSDT	binance	5306.86	5306.87	5306.865	2026-03-01 15:13:40.818156
06bad65f-0411-47e7-abb9-2cddaada45bb	XAUUSDT	binance	5306.6	5306.61	5306.605	2026-03-01 15:13:42.977734
2ced0472-0d39-42aa-a1a0-9e821ac4082a	XAUUSDT	binance	5306.6	5306.61	5306.605	2026-03-01 15:13:43.780119
8c6a731c-9cae-45e1-b1c4-dc2e4e1fef90	XAUUSDT	binance	5306.6	5306.61	5306.605	2026-03-01 15:13:44.059219
5ea5bf1d-d5b2-4781-9937-22fe27f7d01a	XAUUSDT	binance	5306.48	5306.49	5306.485	2026-03-01 15:13:45.830684
8dcf32ec-eb62-4f5d-a616-fb76ddb98e0c	XAUUSDT	binance	5306.48	5306.49	5306.485	2026-03-01 15:13:47.988124
cd10bdb0-bbc4-44af-81a4-4b6c132280da	XAUUSDT	binance	5306.48	5306.49	5306.485	2026-03-01 15:13:48.807474
1e82d86a-8319-4215-86c3-808d2803afcb	XAUUSDT	binance	5306.48	5306.49	5306.485	2026-03-01 15:13:49.054554
394c9fff-3e75-47ae-8145-18b68c86f6d2	XAUUSDT	binance	5306.71	5306.72	5306.715	2026-03-01 15:13:50.851413
417475a5-c352-46dd-9b84-d4253422e353	XAUUSDT	binance	5306.95	5306.96	5306.955	2026-03-01 15:13:52.975218
36a1c841-f6fb-45d2-a2e4-5e543f80aafc	XAUUSDT	binance	5306.27	5306.28	5306.275	2026-03-01 15:13:53.811431
14230b9e-4504-47c5-a788-d75d8270648d	XAUUSDT	binance	5306.27	5306.28	5306.275	2026-03-01 15:13:54.064461
d115e5fe-b84b-4488-8b99-f8e712d56d01	XAUUSDT	binance	5306.27	5306.28	5306.275	2026-03-01 15:13:55.858894
c703363c-91f5-4c7d-a565-027b13d29884	XAUUSDT	binance	5306.27	5306.28	5306.275	2026-03-01 15:13:57.992114
2be25fa7-7476-49ff-80a7-a101648d6515	XAUUSDT	binance	5306.27	5306.28	5306.275	2026-03-01 15:13:58.817504
fdaba107-3786-47b2-bd40-176732ef4021	XAUUSDT	binance	5306.27	5306.28	5306.275	2026-03-01 15:13:59.073032
c35cf375-eae0-4c04-aece-f78fd4fbff8a	XAUUSDT	binance	5306.27	5306.28	5306.275	2026-03-01 15:14:00.868306
93c0c414-b361-4387-b166-5713ad40ffc8	XAUUSDT	binance	5306.27	5306.28	5306.275	2026-03-01 15:14:02.978967
5e00714d-61c2-4675-9e15-091a81cc5f60	XAUUSDT	binance	5306.27	5306.28	5306.275	2026-03-01 15:14:03.807262
84517d8a-8d7d-4956-b431-b784d4ccb123	XAUUSDT	binance	5306.27	5306.28	5306.275	2026-03-01 15:14:04.079153
e4208091-4141-4c6e-b065-c0a9a68e3c41	XAUUSDT	binance	5306.27	5306.28	5306.275	2026-03-01 15:14:05.860638
ff6b4b40-8b7c-483c-925f-af2b3b729313	XAUUSDT	binance	5306.27	5306.28	5306.275	2026-03-01 15:14:07.984533
12894241-8c0d-4fdf-9ca8-c8dd12762f19	XAUUSDT	binance	5306.27	5306.28	5306.275	2026-03-01 15:14:08.819474
5f5f99b6-8cd5-4e24-8ec6-293726352179	XAUUSDT	binance	5306.27	5306.28	5306.275	2026-03-01 15:14:09.070319
bec0fb68-451d-4b81-9047-b867a70df705	XAUUSDT	binance	5306.27	5306.28	5306.275	2026-03-01 15:14:10.860304
26d0f3ce-da23-478e-9d6d-417922b8179b	XAUUSDT	binance	5306.27	5306.28	5306.275	2026-03-01 15:14:12.997121
69ea0f60-401d-42a2-9acf-7bdba736431b	XAUUSDT	binance	5306.27	5306.28	5306.275	2026-03-01 15:14:13.844639
68458601-1eef-49d5-8d10-f54a3bc6c731	XAUUSDT	binance	5306.27	5306.28	5306.275	2026-03-01 15:14:14.096842
989f52e9-b83d-423c-accd-cced0ed77b46	XAUUSDT	binance	5306.39	5306.4	5306.395	2026-03-01 15:14:18.005945
b07d7766-3a1c-4520-89b0-521bf2dd5aba	XAUUSDT	binance	5306.39	5306.4	5306.395	2026-03-01 15:14:18.841933
9d7a32a2-c473-4800-9231-fa89df8900f9	XAUUSDT	binance	5306.39	5306.4	5306.395	2026-03-01 15:14:19.094747
4750c3cc-ce34-4e55-b829-695bbf88c07a	XAUUSDT	binance	5306.39	5306.4	5306.395	2026-03-01 15:14:23.005375
f578f972-9bb6-4040-a1d7-db146a8007e3	XAUUSDT	binance	5306.39	5306.4	5306.395	2026-03-01 15:14:23.841048
43069681-832d-439f-9f61-7a785316e9ef	XAUUSDT	binance	5306.39	5306.4	5306.395	2026-03-01 15:14:24.068852
394d10f2-c255-4ead-af22-6aed3abe5154	XAUUSDT	binance	5306.27	5306.28	5306.275	2026-03-01 15:14:25.835862
93125922-31b8-4fb3-9de2-223fa9e22cb1	XAUUSDT	binance	5306.39	5306.4	5306.395	2026-03-01 15:14:28.016684
97d37de2-8c40-4a37-a05b-f00a3532fd4e	XAUUSDT	binance	5306.39	5306.4	5306.395	2026-03-01 15:14:28.835641
e6689929-47b4-4197-8055-e42b9ffcd255	XAUUSDT	binance	5306.39	5306.4	5306.395	2026-03-01 15:14:29.08839
db37400a-d71e-4119-b7d1-a373cc0a1e45	XAUUSDT	binance	5306.59	5306.6	5306.595	2026-03-01 15:14:33.016513
6f166d1c-67d4-464e-b2d2-5b2dbc9a1a9a	XAUUSDT	binance	5306.59	5306.6	5306.595	2026-03-01 15:14:33.835884
13f0aa9a-8787-4cef-ace4-c74eb94b66c3	XAUUSDT	binance	5306.59	5306.6	5306.595	2026-03-01 15:14:38.834326
a4ac66cf-7b6d-4948-8b84-c58edc4c2f62	XAUUSDT	binance	5306.59	5306.6	5306.595	2026-03-01 15:14:43.831117
674fb513-e380-47f8-84b8-89ef5b85767c	XAUUSDT	binance	5306.59	5306.6	5306.595	2026-03-01 15:14:34.073256
c9cba3df-a4bd-4b28-859d-b6044688259e	XAUUSDT	binance	5306.59	5306.6	5306.595	2026-03-01 15:14:39.070588
0927ed52-e5cf-4c97-8bb1-34a18c9a3c61	XAUUSDT	binance	5306.59	5306.6	5306.595	2026-03-01 15:14:44.097759
e163e205-84d4-443e-a377-f727789b0fb7	XAUUSDT	binance	5306.39	5306.4	5306.395	2026-03-01 15:14:35.774355
2ee35574-10ba-4c34-9dc2-a2b458d8e384	XAUUSDT	binance	5306.59	5306.6	5306.595	2026-03-01 15:14:40.787215
9a29d20d-5775-4cce-9d9d-e765d6e5ef36	XAUUSDT	binance	5306.59	5306.6	5306.595	2026-03-01 15:14:38.016669
75dda6a2-616b-4112-9ddb-d8b9b93e18f9	XAUUSDT	binance	5306.59	5306.6	5306.595	2026-03-01 15:14:43.010644
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
ec2adfd4-65bf-4773-b219-e8cedd4477c9	1ce0146d-b2cb-467d-8b34-ff951e696563	XAUUSD.s	buy	market	5146.56	0.01	0.01	filled	10009492492	2026-02-23 11:12:52	2026-02-26 21:33:02.836833	0.0051465600000000005	sync
01020723-6dee-427e-a88f-6fc4832f944e	1ce0146d-b2cb-467d-8b34-ff951e696563	XAUUSD.s	sell	market	5146.71	0.01	0.01	filled	10009492702	2026-02-23 11:14:19	2026-02-26 21:33:02.836833	0.0051467100000000005	sync
2ac0ae69-f087-4488-8834-c08fc145f829	1ce0146d-b2cb-467d-8b34-ff951e696563	XAUUSD.s	buy	market	5147.51	0.01	0.01	filled	10009493362	2026-02-23 11:28:04	2026-02-26 21:33:02.836833	0.005147510000000001	sync
98ab416a-29bf-406b-aa2b-772b8cbd88c4	1ce0146d-b2cb-467d-8b34-ff951e696563	XAUUSD.s	sell	market	5147.55	0.01	0.01	filled	10009493365	2026-02-23 11:28:18	2026-02-26 21:33:02.836833	0.005147550000000001	sync
c5729d45-085a-4998-8a28-7be85b39deee	c3b7d20d-787a-4bdd-9f92-d73716630bcf	XAUUSDT	buy		5153.15	0.01	0.01	filled	856023384	2026-02-23 11:35:02.752	2026-02-26 21:33:02.836833	0.01288287	sync
2eb60ee0-4b3b-4069-b1c1-bb5636634176	c3b7d20d-787a-4bdd-9f92-d73716630bcf	XAUUSDT	sell		5153.24	0.01	0.01	filled	856122959	2026-02-23 11:41:23.34	2026-02-26 21:33:02.836833	0.0128831	sync
13cb9d13-883d-474a-870d-b3a6e4bb5a24	c3b7d20d-787a-4bdd-9f92-d73716630bcf	XAUUSDT	sell		5175.7	0.822	0.822	filled	950339363	2026-02-26 11:20:06.341	2026-02-26 21:33:02.836833	1.06360634	sync
6bc1fe12-c53e-46a3-bfa4-7ebb7e95f0c0	c3b7d20d-787a-4bdd-9f92-d73716630bcf	XAUUSDT	sell		5175.7	0.178	0.178	filled	950339363	2026-02-26 11:20:06.341	2026-02-26 21:33:02.836833	0.23031865	sync
2d1ed903-230e-4f1a-a9c7-df7e83528953	c3b7d20d-787a-4bdd-9f92-d73716630bcf	XAUUSDT	buy		5174.27	0.105	0.105	filled	950596135	2026-02-26 11:35:20.331	2026-02-26 21:33:02.836833	0.13582458	sync
c30a4807-04df-4189-bd85-145dbed4e931	c3b7d20d-787a-4bdd-9f92-d73716630bcf	XAUUSDT	buy		5174.27	0.078	0.078	filled	950596135	2026-02-26 11:35:20.331	2026-02-26 21:33:02.836833	0.10089826	sync
836d352e-d8b0-4b23-b10b-378a87ac0b15	c3b7d20d-787a-4bdd-9f92-d73716630bcf	XAUUSDT	buy		5174.27	0.121	0.121	filled	950596135	2026-02-26 11:35:20.331	2026-02-26 21:33:02.836833	0.15652166	sync
7bd0a177-0b9e-4a13-890b-678f956f0441	c3b7d20d-787a-4bdd-9f92-d73716630bcf	XAUUSDT	buy		5174.27	0.12	0.12	filled	950596135	2026-02-26 11:35:20.331	2026-02-26 21:33:02.836833	0.1552281	sync
37f3b7bd-b65c-4510-85c3-73c12dd3a857	c3b7d20d-787a-4bdd-9f92-d73716630bcf	XAUUSDT	buy		5174.27	0.121	0.121	filled	950596135	2026-02-26 11:35:20.331	2026-02-26 21:33:02.836833	0.15652166	sync
134b4a1f-925f-4775-9888-e441e74def67	c3b7d20d-787a-4bdd-9f92-d73716630bcf	XAUUSDT	buy		5174.27	0.455	0.455	filled	950596135	2026-02-26 11:35:20.331	2026-02-26 21:33:02.836833	0.58857321	sync
480154a6-884c-4b6b-904f-a32edb5d2506	c3b7d20d-787a-4bdd-9f92-d73716630bcf	XAUUSDT	sell		5166.5	0.06	0.06	filled	955183865	2026-02-26 14:13:52.159	2026-02-26 21:33:02.836833	0.0774975	sync
1477a0d8-bc93-4b6c-91b5-8173bd667c5c	c3b7d20d-787a-4bdd-9f92-d73716630bcf	XAUUSDT	sell		5166.5	0.001	0.001	filled	955183865	2026-02-26 14:13:52.159	2026-02-26 21:33:02.836833	0.00129162	sync
bbe3930b-c37b-4c74-a615-87bc9c0d9e32	c3b7d20d-787a-4bdd-9f92-d73716630bcf	XAUUSDT	sell		5166.5	0.193	0.193	filled	955183865	2026-02-26 14:13:52.159	2026-02-26 21:33:02.836833	0.24928362	sync
70fb1200-6106-434f-bbc9-41e74e4266ba	c3b7d20d-787a-4bdd-9f92-d73716630bcf	XAUUSDT	sell		5166.5	0.746	0.746	filled	955183865	2026-02-26 14:13:54.972	2026-02-26 21:33:02.836833	0	sync
feca8740-1850-4f8f-bbdb-510c406ed090	c3b7d20d-787a-4bdd-9f92-d73716630bcf	XAUUSDT	buy		5166.65	0.839	0.839	filled	955348868	2026-02-26 14:20:10.347	2026-02-26 21:33:02.836833	1.08370483	sync
f76e7543-c58f-44b3-b327-4924c1f6fa93	c3b7d20d-787a-4bdd-9f92-d73716630bcf	XAUUSDT	buy		5166.65	0.161	0.161	filled	955348868	2026-02-26 14:20:10.347	2026-02-26 21:33:02.836833	0.20795766	sync
bddcfdcb-7164-4566-826d-022a48898b12	c3b7d20d-787a-4bdd-9f92-d73716630bcf	XAUUSDT	sell		5160.95	0.966	0.966	filled	957835393	2026-02-26 15:21:02.509	2026-02-26 21:33:02.836833	1.24636942	sync
004b91b6-2cdb-4a32-937c-a525b3c20bba	c3b7d20d-787a-4bdd-9f92-d73716630bcf	XAUUSDT	sell		5160.95	0.001	0.001	filled	957835393	2026-02-26 15:21:02.509	2026-02-26 21:33:02.836833	0.00129023	sync
f5d08d1c-7ede-4730-87ed-3df43f71dea0	c3b7d20d-787a-4bdd-9f92-d73716630bcf	XAUUSDT	sell		5160.95	0.033	0.033	filled	957835393	2026-02-26 15:21:02.509	2026-02-26 21:33:02.836833	0.04257783	sync
305521d6-412b-4ea4-ab8d-9df72420fdf9	c3b7d20d-787a-4bdd-9f92-d73716630bcf	XAUUSDT	buy		5158.85	0.439	0.439	filled	957872864	2026-02-26 15:21:45.375	2026-02-26 21:33:02.836833	0.56618378	sync
ae24697a-4c82-4843-b7ae-b917a3adb969	c3b7d20d-787a-4bdd-9f92-d73716630bcf	XAUUSDT	buy		5158.85	0.561	0.561	filled	957872864	2026-02-26 15:21:45.375	2026-02-26 21:33:02.836833	0.72352871	sync
45662d32-e6e9-4491-8c82-4aa4f1ad1b88	c3b7d20d-787a-4bdd-9f92-d73716630bcf	XAUUSDT	sell		5185.52	0.084	0.084	filled	961080739	2026-02-26 16:42:59.458	2026-02-26 21:33:02.836833	0.10889592	sync
ace2a91d-dfe4-49e6-8259-b413b867046c	c3b7d20d-787a-4bdd-9f92-d73716630bcf	XAUUSDT	sell		5185.52	0.916	0.916	filled	961080739	2026-02-26 16:42:59.458	2026-02-26 21:33:02.836833	1.18748408	sync
ddf36347-0cd0-474e-96a6-d748efc5fb51	c3b7d20d-787a-4bdd-9f92-d73716630bcf	XAUUSDT	buy		5184.64	0.002	0.002	filled	961095493	2026-02-26 16:43:23.831	2026-02-26 21:33:02.836833	0.00259232	sync
2f7c1de4-1e08-4967-9378-375969625ed2	c3b7d20d-787a-4bdd-9f92-d73716630bcf	XAUUSDT	buy		5184.64	0.979	0.979	filled	961095493	2026-02-26 16:43:23.831	2026-02-26 21:33:02.836833	1.26894064	sync
aca41258-5a9e-4b35-b651-47a32d38e51d	c3b7d20d-787a-4bdd-9f92-d73716630bcf	XAUUSDT	buy		5184.64	0.006	0.006	filled	961095493	2026-02-26 16:43:23.831	2026-02-26 21:33:02.837847	0.00777696	sync
15478811-d8b2-4e5e-aa4d-43199094043b	c3b7d20d-787a-4bdd-9f92-d73716630bcf	XAUUSDT	buy		5184.64	0.013	0.013	filled	961095493	2026-02-26 16:43:23.831	2026-02-26 21:33:02.837847	0.01685008	sync
60106614-c564-4922-822b-e8623635a8e8	c3b7d20d-787a-4bdd-9f92-d73716630bcf	XAUUSDT	sell		5180.09	0.969	0.969	filled	961244807	2026-02-26 16:48:38.626	2026-02-26 21:33:02.837847	1.2548768	sync
21495dd3-c257-4021-b4f2-887b5d7f02fe	c3b7d20d-787a-4bdd-9f92-d73716630bcf	XAUUSDT	sell		5180.09	0.031	0.031	filled	961244807	2026-02-26 16:48:38.626	2026-02-26 21:33:02.837847	0.04014569	sync
ea167751-c33e-4542-9e34-4ca2651d0db1	c3b7d20d-787a-4bdd-9f92-d73716630bcf	XAUUSDT	buy		5178.52	0.786	0.786	filled	961380901	2026-02-26 16:53:26.281	2026-02-26 21:33:02.837847	1.01757918	sync
be93da2b-c30e-4dd9-aa7a-31089a5fb442	c3b7d20d-787a-4bdd-9f92-d73716630bcf	XAUUSDT	buy		5178.57	0.214	0.214	filled	961380901	2026-02-26 16:53:26.281	2026-02-26 21:33:02.837847	0.27705349	sync
0041a4d1-958a-496f-9f1d-d5a289c58c4b	c3b7d20d-787a-4bdd-9f92-d73716630bcf	XAUUSDT	sell		5182.82	0.628	0.628	filled	961622691	2026-02-26 17:03:02.379	2026-02-26 21:33:02.837847	0.81370274	sync
3c2e4d82-07bb-44a7-af85-0ac12da66c88	c3b7d20d-787a-4bdd-9f92-d73716630bcf	XAUUSDT	sell		5182.82	0.372	0.372	filled	961622691	2026-02-26 17:03:02.379	2026-02-26 21:33:02.837847	0.48200226	sync
15281cb3-0ca6-48bf-b95d-2224d96e2aa6	c3b7d20d-787a-4bdd-9f92-d73716630bcf	XAUUSDT	buy		5181.35	0.616	0.616	filled	961949236	2026-02-26 17:14:50.267	2026-02-26 21:33:02.837847	0.7979279	sync
c6505b37-ce9e-44c3-bd66-daa79d73e9f9	c3b7d20d-787a-4bdd-9f92-d73716630bcf	XAUUSDT	buy		5181.35	0.001	0.001	filled	961949236	2026-02-26 17:14:50.267	2026-02-26 21:33:02.837847	0.00129533	sync
76c26056-b66d-4df4-823b-e34c731bf8dc	c3b7d20d-787a-4bdd-9f92-d73716630bcf	XAUUSDT	buy		5181.35	0.003	0.003	filled	961949236	2026-02-26 17:14:50.267	2026-02-26 21:33:02.837847	0.00388601	sync
bb03137d-d34a-4726-8d35-484bd6693c4e	c3b7d20d-787a-4bdd-9f92-d73716630bcf	XAUUSDT	buy		5181.35	0.38	0.38	filled	961949236	2026-02-26 17:14:50.267	2026-02-26 21:33:02.837847	0.49222825	sync
bf385e66-3bd9-48a6-8bfb-ca7fe4932ce1	c3b7d20d-787a-4bdd-9f92-d73716630bcf	XAUUSDT	sell		5176.49	0.001	0.001	filled	962753255	2026-02-26 17:41:27.732	2026-02-26 21:33:02.837847	0.00129412	sync
dee683b6-5754-408f-b8ea-a086491a84bf	c3b7d20d-787a-4bdd-9f92-d73716630bcf	XAUUSDT	sell		5176.49	0.928	0.928	filled	962753255	2026-02-26 17:41:27.732	2026-02-26 21:33:02.837847	1.20094568	sync
1277500b-5167-4990-9bf7-ce377b07f9d7	c3b7d20d-787a-4bdd-9f92-d73716630bcf	XAUUSDT	sell		5176.49	0.071	0.071	filled	962753255	2026-02-26 17:41:27.732	2026-02-26 21:33:02.837847	0.09188269	sync
da185213-71c1-401c-ab45-ce4338340611	c3b7d20d-787a-4bdd-9f92-d73716630bcf	XAUUSDT	buy		5175.39	0.594	0.594	filled	962761050	2026-02-26 17:41:46.578	2026-02-26 21:33:02.837847	0.76854541	sync
347d7d37-ce3a-4878-88c4-26c64a957fbd	c3b7d20d-787a-4bdd-9f92-d73716630bcf	XAUUSDT	buy		5175.39	0.406	0.406	filled	962761050	2026-02-26 17:41:46.578	2026-02-26 21:33:02.837847	0.52530208	sync
3e269867-d245-415e-99fa-9aff064c21fd	c3b7d20d-787a-4bdd-9f92-d73716630bcf	XAUUSDT	sell		5165.85	1	1	filled	963277848	2026-02-26 17:57:08.09	2026-02-26 21:33:02.837847	1.2914625	sync
5dd1fe81-9560-45d1-bb9a-76003dbdc856	c3b7d20d-787a-4bdd-9f92-d73716630bcf	XAUUSDT	buy		5164.06	1	1	filled	963298997	2026-02-26 17:57:40.252	2026-02-26 21:33:02.837847	1.291015	sync
4bb33684-42b2-4164-ad1c-45ea42aa1f1b	c3b7d20d-787a-4bdd-9f92-d73716630bcf	XAUUSDT	sell		5167.84	0.807	0.807	filled	963643663	2026-02-26 18:08:45.796	2026-02-26 21:33:02.837847	1.04261172	sync
633cee83-8a09-4b4c-8b20-d217db613ccc	c3b7d20d-787a-4bdd-9f92-d73716630bcf	XAUUSDT	sell		5167.84	0.193	0.193	filled	963643663	2026-02-26 18:08:45.796	2026-02-26 21:33:02.837847	0.24934828	sync
fdab88d6-071b-49a3-be4a-7dffc2b5534f	c3b7d20d-787a-4bdd-9f92-d73716630bcf	XAUUSDT	buy		5167.53	0.594	0.594	filled	964445521	2026-02-26 18:34:48.704	2026-02-26 21:33:02.837847	0.7673782	sync
94b2b593-3b7d-4f1b-ba86-c34828326b78	c3b7d20d-787a-4bdd-9f92-d73716630bcf	XAUUSDT	buy		5167.53	0.406	0.406	filled	964445521	2026-02-26 18:34:48.704	2026-02-26 21:33:02.837847	0.52450429	sync
21c59eca-6cc1-4c1d-9397-b9f7a1841dea	c3b7d20d-787a-4bdd-9f92-d73716630bcf	XAUUSDT	sell		5167.19	0.238	0.238	filled	964507177	2026-02-26 18:35:52.722	2026-02-26 21:33:02.837847	0.3074478	sync
b3f7b8e8-9139-458d-be30-853a732cd708	c3b7d20d-787a-4bdd-9f92-d73716630bcf	XAUUSDT	sell		5167.19	0.08	0.08	filled	964507177	2026-02-26 18:35:52.722	2026-02-26 21:33:02.837847	0.1033438	sync
ac758eb4-077e-4309-97e5-6b23ccc8bbd1	c3b7d20d-787a-4bdd-9f92-d73716630bcf	XAUUSDT	sell		5167.19	0.002	0.002	filled	964507177	2026-02-26 18:35:52.722	2026-02-26 21:33:02.837847	0.00258359	sync
3b6471ef-144e-4968-ab9e-19f917a79892	c3b7d20d-787a-4bdd-9f92-d73716630bcf	XAUUSDT	sell		5167.19	0.001	0.001	filled	964507177	2026-02-26 18:35:52.722	2026-02-26 21:33:02.837847	0.00129179	sync
7de8ad56-f8e8-4843-a068-59b6f3faa551	c3b7d20d-787a-4bdd-9f92-d73716630bcf	XAUUSDT	sell		5167.19	0.022	0.022	filled	964507177	2026-02-26 18:35:52.722	2026-02-26 21:33:02.837847	0.02841954	sync
4330a1a2-46c8-4b73-917d-4d3ddbde74e2	c3b7d20d-787a-4bdd-9f92-d73716630bcf	XAUUSDT	sell		5167.19	0.657	0.657	filled	964507177	2026-02-26 18:35:52.722	2026-02-26 21:33:02.837847	0.84871095	sync
7f14d104-1622-4a0f-967a-35944174e68e	c3b7d20d-787a-4bdd-9f92-d73716630bcf	XAUUSDT	buy		5186.62	0.001	0.001	filled	965326997	2026-02-26 19:05:24.001	2026-02-26 21:33:02.837847	0.00129665	sync
87e1fe98-d82d-4733-9339-a821fc326fcc	c3b7d20d-787a-4bdd-9f92-d73716630bcf	XAUUSDT	buy		5186.62	0.002	0.002	filled	965326997	2026-02-26 19:05:24.001	2026-02-26 21:33:02.837847	0.00259331	sync
23bab106-0ee5-40ba-be55-1dec29fb9cca	c3b7d20d-787a-4bdd-9f92-d73716630bcf	XAUUSDT	buy		5186.62	0.192	0.192	filled	965326997	2026-02-26 19:05:24.001	2026-02-26 21:33:02.837847	0.24895776	sync
c0056d0b-d1a8-4e71-9302-dfefdc3032b8	c3b7d20d-787a-4bdd-9f92-d73716630bcf	XAUUSDT	buy		5186.62	0.002	0.002	filled	965326997	2026-02-26 19:05:24.001	2026-02-26 21:33:02.837847	0.00259331	sync
3f0b1ab7-4a7b-4801-99cf-deb10ddd37db	c3b7d20d-787a-4bdd-9f92-d73716630bcf	XAUUSDT	buy		5186.62	0.002	0.002	filled	965326997	2026-02-26 19:05:24.001	2026-02-26 21:33:02.837847	0.00259331	sync
e2dc66d4-5c3f-42a9-b4cf-17a387fd2c9f	c3b7d20d-787a-4bdd-9f92-d73716630bcf	XAUUSDT	buy		5186.62	0.002	0.002	filled	965326997	2026-02-26 19:05:24.001	2026-02-26 21:33:02.837847	0.00259331	sync
0edef75d-fc3f-496a-9b1e-c60262306dd6	c3b7d20d-787a-4bdd-9f92-d73716630bcf	XAUUSDT	buy		5186.62	0.003	0.003	filled	965326997	2026-02-26 19:05:24.001	2026-02-26 21:33:02.837847	0.00388996	sync
c10cd50e-5bbc-4d69-abe0-963d7db9c27a	c3b7d20d-787a-4bdd-9f92-d73716630bcf	XAUUSDT	buy		5186.62	0.796	0.796	filled	965326997	2026-02-26 19:05:24.001	2026-02-26 21:33:02.837847	1.03213738	sync
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
7ad1f933-1522-497b-b668-765a416f9d04	控制面板	menu:dashboard	menu	/dashboard	\N	访问控制面板	\N	0	t	2026-02-25 11:01:42.595699	2026-02-25 11:01:42.595699
ee39bc5a-aad7-43ad-8294-04e88f982e56	交易历史数据	menu:trading_history	menu	/trading-history	\N	访问交易历史数据页面	\N	0	t	2026-02-25 11:01:42.59996	2026-02-25 11:01:42.59996
e01b31b8-f5c2-4b3d-8eae-b35eb12bc268	挂单查询	menu:pending_orders	menu	/pending-orders	\N	访问挂单查询页面	\N	0	t	2026-02-25 11:01:42.60344	2026-02-25 11:01:42.60344
afcd3a39-93d8-4328-9b41-54dc3243551c	策略控制	menu:strategy_control	menu	/strategy	\N	访问策略控制页面	\N	0	t	2026-02-25 11:01:42.604894	2026-02-25 11:01:42.604894
e8d71861-f149-4110-ad02-a12e9f74f62f	点差记录分析	menu:spread_analysis	menu	/spread-analysis	\N	访问点差记录分析页面	\N	0	t	2026-02-25 11:01:42.606184	2026-02-25 11:01:42.606184
594f4900-5252-4a91-a462-707052a4c5d9	账户管理	menu:account_management	menu	/accounts	\N	访问账户管理页面	\N	0	t	2026-02-25 11:01:42.60748	2026-02-25 11:01:42.60748
3a295541-7916-4fb6-ba4c-4b0512d70c84	风控管理	menu:risk_management	menu	/risk	\N	访问风控管理页面	\N	0	t	2026-02-25 11:01:42.608919	2026-02-25 11:01:42.608919
9f58c27a-2443-463e-85af-49edfc2e5e7c	系统管理	menu:system_management	menu	/system	\N	访问系统管理页面	\N	0	t	2026-02-25 11:01:42.610145	2026-02-25 11:01:42.610145
09070d89-9465-4210-80ab-631cb7589e80	查看角色详情	role:detail	api	/api/v1/rbac/roles/{id}	\N	\N	\N	0	t	2026-02-25 17:47:03.998591	2026-02-25 17:47:03.998591
bb580d29-f140-4664-9f9d-61459971cd91	查看权限列表	permission:list	api	/api/v1/rbac/permissions	\N	\N	\N	0	t	2026-02-25 17:47:04.008244	2026-02-25 17:47:04.008244
e63b6f2e-78dc-479c-904e-9f22f9b7b21a	创建权限	permission:create	api	/api/v1/rbac/permissions	\N	\N	\N	0	t	2026-02-25 17:47:04.009258	2026-02-25 17:47:04.009258
3374bf53-16bd-47f2-91b5-f8190f38554b	更新权限	permission:update	api	/api/v1/rbac/permissions/{id}	\N	\N	\N	0	t	2026-02-25 17:47:04.011259	2026-02-25 17:47:04.011259
9933b355-d93d-4bed-87d8-3595fc72ee00	删除权限	permission:delete	api	/api/v1/rbac/permissions/{id}	\N	\N	\N	0	t	2026-02-25 17:47:04.012247	2026-02-25 17:47:04.012247
8662b74a-6abe-45a5-b2c7-98f621d8320a	查看策略列表	strategy:list	api	/api/v1/strategies	\N	\N	\N	0	t	2026-02-25 17:47:04.015258	2026-02-25 17:47:04.015258
5908338f-ddd4-4683-ac52-f8d7ceb897a1	创建策略	strategy:create	api	/api/v1/strategies	\N	\N	\N	0	t	2026-02-25 17:47:04.016243	2026-02-25 17:47:04.016243
2511d363-1467-4683-9fb7-aec385271e03	更新策略	strategy:update	api	/api/v1/strategies/{id}	\N	\N	\N	0	t	2026-02-25 17:47:04.017245	2026-02-25 17:47:04.017245
898e3a3b-54e7-49a4-adff-a02e09a04800	删除策略	strategy:delete	api	/api/v1/strategies/{id}	\N	\N	\N	0	t	2026-02-25 17:47:04.019243	2026-02-25 17:47:04.019243
6793ba9e-25be-4436-960e-370a0ed6c013	交易菜单	menu:trading	menu	/trading	\N	\N	\N	0	t	2026-02-25 17:47:04.020246	2026-02-25 17:47:04.020246
52b3e485-e445-406e-8d6d-c5c3b55361f4	策略菜单	menu:strategies	menu	/strategies	\N	\N	\N	0	t	2026-02-25 17:47:04.021244	2026-02-25 17:47:04.021244
b6e6307e-3b55-4794-bc7e-1f793192a75d	持仓菜单	menu:positions	menu	/positions	\N	\N	\N	0	t	2026-02-25 17:47:04.023238	2026-02-25 17:47:04.023238
e2bf1c97-a00b-4afa-a9c5-8e0e08d59f5a	账户菜单	menu:accounts	menu	/accounts	\N	\N	\N	0	t	2026-02-25 17:47:04.024243	2026-02-25 17:47:04.024243
5626f997-f5c0-410a-af8b-39add82f8cec	风控菜单	menu:risk	menu	/risk	\N	\N	\N	0	t	2026-02-25 17:47:04.025243	2026-02-25 17:47:04.025243
27178daf-3255-41e6-bb32-8f408d49bd9d	系统管理菜单	menu:system	menu	/system	\N	\N	\N	0	t	2026-02-25 17:47:04.026245	2026-02-25 17:47:04.026245
035ce5bf-b2e0-42af-aa22-b5c221e6d640	权限管理菜单	menu:rbac	menu	/rbac	\N	\N	\N	0	t	2026-02-25 17:47:04.028245	2026-02-25 17:47:04.028245
88bb13ee-b611-44ae-a58e-94e70243b896	安全组件菜单	menu:security	menu	/security	\N	\N	\N	0	t	2026-02-25 17:47:04.029242	2026-02-25 17:47:04.029242
9cadd170-eaf6-49fe-9504-2afc8766a6b2	SSL证书菜单	menu:ssl	menu	/ssl	\N	\N	\N	0	t	2026-02-25 17:47:04.030245	2026-02-25 17:47:04.030245
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
-- Data for Name: risk_alerts; Type: TABLE DATA; Schema: public; Owner: postgres
--

COPY public.risk_alerts (alert_id, user_id, alert_level, alert_message, create_time, expire_time) FROM stdin;
\.


--
-- Data for Name: risk_settings; Type: TABLE DATA; Schema: public; Owner: postgres
--

COPY public.risk_settings (settings_id, user_id, binance_net_asset, bybit_mt5_net_asset, total_net_asset, binance_liquidation_price, bybit_mt5_liquidation_price, mt5_lag_count, reverse_open_price, reverse_open_sync_count, reverse_close_price, reverse_close_sync_count, forward_open_price, forward_open_sync_count, forward_close_price, forward_close_sync_count, create_time, update_time, spread_alert_sound, net_asset_alert_sound, mt5_alert_sound, liquidation_alert_sound, spread_alert_repeat_count, net_asset_alert_repeat_count, mt5_alert_repeat_count, liquidation_alert_repeat_count, single_leg_alert_sound, single_leg_alert_repeat_count) FROM stdin;
4561c5cf-8203-4ed8-8e85-62d6b6576fec	0bc9c5f7-dc77-4f7d-bfbf-4b347a934b24	50	50	300	2000	2000	5	4	3	4	3	4	3	4	3	2026-02-20 17:51:35.678918	2026-02-27 10:00:51.323264	/uploads/alert_sounds/0bc9c5f7-dc77-4f7d-bfbf-4b347a934b24_spread.mp3	/uploads/alert_sounds/0bc9c5f7-dc77-4f7d-bfbf-4b347a934b24_net_asset.mp3	/uploads/alert_sounds/0bc9c5f7-dc77-4f7d-bfbf-4b347a934b24_mt5.mp3	/uploads/alert_sounds/0bc9c5f7-dc77-4f7d-bfbf-4b347a934b24_liquidation.mp3	3	3	3	3	/uploads/alert_sounds/0bc9c5f7-dc77-4f7d-bfbf-4b347a934b24_single_leg.mp3	3
\.


--
-- Data for Name: role_permissions; Type: TABLE DATA; Schema: public; Owner: postgres
--

COPY public.role_permissions (id, role_id, permission_id, granted_at, granted_by) FROM stdin;
e80f832a-a45b-40b7-a100-c4777370021d	8e25c438-70a5-4d9b-8634-9f16ab2cb1f3	c060adfa-d126-4366-8b59-f557cdb6f908	2026-02-25 17:47:04.04393	\N
bf1a3760-ba6e-4b35-904b-c6cb7145c0ad	8e25c438-70a5-4d9b-8634-9f16ab2cb1f3	bdf67ee9-71ba-4892-b499-4cf048c3f0fc	2026-02-25 17:47:04.053915	\N
028858c4-ecb0-46b9-a7ab-2e653efcc042	8e25c438-70a5-4d9b-8634-9f16ab2cb1f3	ae04fb5d-e4ef-4173-91ec-168aa812c17f	2026-02-25 17:47:04.05492	\N
4ed53824-d77b-4ea5-b49a-ca91b4acafee	8e25c438-70a5-4d9b-8634-9f16ab2cb1f3	6d83db88-d70b-49c9-8b98-ad617f49a24f	2026-02-25 17:47:04.055921	\N
94ad8c81-da35-4578-9b07-64d424b805b2	8e25c438-70a5-4d9b-8634-9f16ab2cb1f3	f05b272c-dfee-4354-a289-4762787789da	2026-02-25 17:47:04.057919	\N
34fd9eac-ec16-4014-a5a2-4b72d7617d1d	8e25c438-70a5-4d9b-8634-9f16ab2cb1f3	aa5381b9-60f0-4cea-8c5f-2274e56a654b	2026-02-25 17:47:04.05892	\N
437614f2-6cf7-44dc-98d6-ef330b671905	8e25c438-70a5-4d9b-8634-9f16ab2cb1f3	09070d89-9465-4210-80ab-631cb7589e80	2026-02-25 17:47:04.059921	\N
5306fc67-9866-451c-a88a-1712294110c5	8e25c438-70a5-4d9b-8634-9f16ab2cb1f3	e3a66a83-0fc3-4973-848d-e0a23de86a52	2026-02-25 17:47:04.061924	\N
174cd705-bbfb-4fdb-b10d-2703acb4e64a	8e25c438-70a5-4d9b-8634-9f16ab2cb1f3	82ad46cb-092f-4487-b272-2daf5541c897	2026-02-25 17:47:04.062922	\N
1ad324c0-5fd0-4984-a621-0b74d703f081	8e25c438-70a5-4d9b-8634-9f16ab2cb1f3	7bd2845d-95e6-4d84-8c40-404910e7a352	2026-02-25 17:47:04.063921	\N
76a598bb-2910-4367-a8c7-213848389770	8e25c438-70a5-4d9b-8634-9f16ab2cb1f3	4c4efc0f-d514-47c6-b4fe-708c6b8e9f9c	2026-02-25 17:47:04.064921	\N
a1b0b7ca-4063-4c05-b232-e9d9d181ff4a	8e25c438-70a5-4d9b-8634-9f16ab2cb1f3	bb580d29-f140-4664-9f9d-61459971cd91	2026-02-25 17:47:04.06592	\N
7e917fac-4028-4e10-bedb-5eea2e12d464	8e25c438-70a5-4d9b-8634-9f16ab2cb1f3	e63b6f2e-78dc-479c-904e-9f22f9b7b21a	2026-02-25 17:47:04.067725	\N
8c178d87-360b-4b90-be3a-2afe0d7c51c8	8e25c438-70a5-4d9b-8634-9f16ab2cb1f3	3374bf53-16bd-47f2-91b5-f8190f38554b	2026-02-25 17:47:04.068751	\N
0daeacee-5025-4e32-bb57-fc1cc4e720cb	8e25c438-70a5-4d9b-8634-9f16ab2cb1f3	9933b355-d93d-4bed-87d8-3595fc72ee00	2026-02-25 17:47:04.069749	\N
6da341d4-a5f7-43b9-9458-d18514c86ed7	8e25c438-70a5-4d9b-8634-9f16ab2cb1f3	a10cceed-9994-40f9-97f8-b85da58309c9	2026-02-25 17:47:04.070748	\N
8e97d49f-1599-4005-86ec-a99417a33741	8e25c438-70a5-4d9b-8634-9f16ab2cb1f3	c1f876b7-82be-4652-b49e-e29f93418adf	2026-02-25 17:47:04.07274	\N
79bf32e8-b5e9-4228-80c1-5e91fd5cf88a	8e25c438-70a5-4d9b-8634-9f16ab2cb1f3	5feb4705-3e15-41f0-abe9-54a687cb8378	2026-02-25 17:47:04.073743	\N
0bf7e1f1-66d1-40ff-9155-a3100f536963	8e25c438-70a5-4d9b-8634-9f16ab2cb1f3	a429e651-676d-470a-b78e-72387bd23921	2026-02-25 17:47:04.074747	\N
62af4fba-86e8-4616-b30d-2cbf73a8d298	8e25c438-70a5-4d9b-8634-9f16ab2cb1f3	97ba4968-c723-4599-9615-849f6da31eae	2026-02-25 17:47:04.075748	\N
754e6030-e6e4-4485-aca6-287e6b635f54	8e25c438-70a5-4d9b-8634-9f16ab2cb1f3	619b5ea4-4839-40ff-88c2-05c940ff3b15	2026-02-25 17:47:04.076747	\N
d116a45b-6477-4a65-9574-ed2bd8ad79a5	8e25c438-70a5-4d9b-8634-9f16ab2cb1f3	fc27a1d1-6ef5-484e-b32b-47f5f3d7e81c	2026-02-25 17:47:04.077747	\N
6d01c05e-41b7-42c1-9793-e8778854689c	8e25c438-70a5-4d9b-8634-9f16ab2cb1f3	0ec6ee5f-2ffa-4dda-9fc4-3162eb855547	2026-02-25 17:47:04.079743	\N
51cd615e-8b4e-408e-8dc6-d0893de213cf	8e25c438-70a5-4d9b-8634-9f16ab2cb1f3	50303ba1-ca2c-491d-81b8-8b95e436c9da	2026-02-25 17:47:04.080745	\N
41234f67-4e81-4f0d-9f49-f7778675d45c	8e25c438-70a5-4d9b-8634-9f16ab2cb1f3	5805e19e-c3e7-4086-bd7a-6a963539ef5e	2026-02-25 17:47:04.081747	\N
b9b32eca-0302-426c-a89e-38ab7dcd819f	8e25c438-70a5-4d9b-8634-9f16ab2cb1f3	8662b74a-6abe-45a5-b2c7-98f621d8320a	2026-02-25 17:47:04.082749	\N
600cd578-ec1b-49ab-bdae-5e4a4be6e00c	8e25c438-70a5-4d9b-8634-9f16ab2cb1f3	5908338f-ddd4-4683-ac52-f8d7ceb897a1	2026-02-25 17:47:04.083748	\N
78d45038-8987-4345-b6ab-52e900927cbd	8e25c438-70a5-4d9b-8634-9f16ab2cb1f3	2511d363-1467-4683-9fb7-aec385271e03	2026-02-25 17:47:04.084748	\N
bdc7292b-6bae-46cb-a2d6-f8e178703f9c	8e25c438-70a5-4d9b-8634-9f16ab2cb1f3	898e3a3b-54e7-49a4-adff-a02e09a04800	2026-02-25 17:47:04.08675	\N
bfe48b84-8376-4926-be70-a21169fc5098	8e25c438-70a5-4d9b-8634-9f16ab2cb1f3	7ad1f933-1522-497b-b668-765a416f9d04	2026-02-25 17:47:04.087746	\N
3877ef59-de6e-4698-b6a5-bb41339a4a9c	8e25c438-70a5-4d9b-8634-9f16ab2cb1f3	6793ba9e-25be-4436-960e-370a0ed6c013	2026-02-25 17:47:04.088747	\N
54ac6091-2f14-4639-a1a7-136d85fa29e2	8e25c438-70a5-4d9b-8634-9f16ab2cb1f3	52b3e485-e445-406e-8d6d-c5c3b55361f4	2026-02-25 17:47:04.089747	\N
2562c91c-87f4-4395-bf91-e782b3de8c98	8e25c438-70a5-4d9b-8634-9f16ab2cb1f3	b6e6307e-3b55-4794-bc7e-1f793192a75d	2026-02-25 17:47:04.090747	\N
d9bed372-23db-44cb-add3-2bec568420b7	8e25c438-70a5-4d9b-8634-9f16ab2cb1f3	e2bf1c97-a00b-4afa-a9c5-8e0e08d59f5a	2026-02-25 17:47:04.091747	\N
a44bd94e-3e08-4f44-bf41-6db464d3c97b	8e25c438-70a5-4d9b-8634-9f16ab2cb1f3	5626f997-f5c0-410a-af8b-39add82f8cec	2026-02-25 17:47:04.092748	\N
eec868c4-f6c5-409f-b467-cf3b4cd7f342	8e25c438-70a5-4d9b-8634-9f16ab2cb1f3	27178daf-3255-41e6-bb32-8f408d49bd9d	2026-02-25 17:47:04.094742	\N
5c50df01-79d5-43b4-a3c5-202304f484a3	8e25c438-70a5-4d9b-8634-9f16ab2cb1f3	035ce5bf-b2e0-42af-aa22-b5c221e6d640	2026-02-25 17:47:04.095746	\N
59b733ff-3ee9-4326-b7ef-75aae0c446bc	8e25c438-70a5-4d9b-8634-9f16ab2cb1f3	88bb13ee-b611-44ae-a58e-94e70243b896	2026-02-25 17:47:04.096747	\N
e6e3e0fd-53aa-479d-8657-517678bfb5a2	8e25c438-70a5-4d9b-8634-9f16ab2cb1f3	9cadd170-eaf6-49fe-9504-2afc8766a6b2	2026-02-25 17:47:04.098768	\N
b103e724-1292-4127-8d80-660a17bb6d26	568d17ae-20ee-438c-b1d1-1afdb0a26bc6	a10cceed-9994-40f9-97f8-b85da58309c9	2026-02-25 17:47:04.125741	\N
9591210b-6b6d-4c4a-86d2-49d449249696	568d17ae-20ee-438c-b1d1-1afdb0a26bc6	c1f876b7-82be-4652-b49e-e29f93418adf	2026-02-25 17:47:04.126738	\N
e456be1d-9c09-423f-ab11-82751cfae0f2	568d17ae-20ee-438c-b1d1-1afdb0a26bc6	5feb4705-3e15-41f0-abe9-54a687cb8378	2026-02-25 17:47:04.12774	\N
0af93efa-a313-4016-aeb7-87e83a101908	568d17ae-20ee-438c-b1d1-1afdb0a26bc6	a429e651-676d-470a-b78e-72387bd23921	2026-02-25 17:47:04.12874	\N
139768ea-db2e-48f7-80d6-95ba63054b0c	568d17ae-20ee-438c-b1d1-1afdb0a26bc6	97ba4968-c723-4599-9615-849f6da31eae	2026-02-25 17:47:04.130429	\N
fa65cb14-913f-4c9f-aaed-c81106b19048	568d17ae-20ee-438c-b1d1-1afdb0a26bc6	619b5ea4-4839-40ff-88c2-05c940ff3b15	2026-02-25 17:47:04.131451	\N
9f11d7b2-cd60-4965-94a8-5c0923fb28f9	568d17ae-20ee-438c-b1d1-1afdb0a26bc6	fc27a1d1-6ef5-484e-b32b-47f5f3d7e81c	2026-02-25 17:47:04.132451	\N
57e0576f-9526-4e2b-aad5-3d20a1bc4fd9	568d17ae-20ee-438c-b1d1-1afdb0a26bc6	0ec6ee5f-2ffa-4dda-9fc4-3162eb855547	2026-02-25 17:47:04.133449	\N
10031932-144e-46fe-ac01-6e5e78c516e2	568d17ae-20ee-438c-b1d1-1afdb0a26bc6	88bb13ee-b611-44ae-a58e-94e70243b896	2026-02-25 17:47:04.134453	\N
92a81cbf-cf96-4602-a42b-90640e642091	568d17ae-20ee-438c-b1d1-1afdb0a26bc6	9cadd170-eaf6-49fe-9504-2afc8766a6b2	2026-02-25 17:47:04.136442	\N
940ffa1b-ece0-4d79-8f0a-73086151d9fb	d3e8bb4a-d6e2-49d5-80b9-ce47d1d2af92	50303ba1-ca2c-491d-81b8-8b95e436c9da	2026-02-25 17:47:04.13845	\N
a23fb09d-4457-41ce-befd-30effe4326d9	d3e8bb4a-d6e2-49d5-80b9-ce47d1d2af92	5805e19e-c3e7-4086-bd7a-6a963539ef5e	2026-02-25 17:47:04.139453	\N
7ca57d19-2a49-4342-aa3a-51393e601aee	d3e8bb4a-d6e2-49d5-80b9-ce47d1d2af92	8662b74a-6abe-45a5-b2c7-98f621d8320a	2026-02-25 17:47:04.140452	\N
02cf2613-5ed8-4e13-ad08-3b81dc0658b1	d3e8bb4a-d6e2-49d5-80b9-ce47d1d2af92	5908338f-ddd4-4683-ac52-f8d7ceb897a1	2026-02-25 17:47:04.142446	\N
f03a8587-8ef6-46d1-a8c5-b0cf0832a9f3	d3e8bb4a-d6e2-49d5-80b9-ce47d1d2af92	2511d363-1467-4683-9fb7-aec385271e03	2026-02-25 17:47:04.143449	\N
a7154370-0825-4e64-8cd3-9b3d3c9412bb	d3e8bb4a-d6e2-49d5-80b9-ce47d1d2af92	898e3a3b-54e7-49a4-adff-a02e09a04800	2026-02-25 17:47:04.144451	\N
b83ad7af-41a8-4903-9b11-82a712e7389c	d3e8bb4a-d6e2-49d5-80b9-ce47d1d2af92	7ad1f933-1522-497b-b668-765a416f9d04	2026-02-25 17:47:04.145448	\N
b351081b-42da-4018-afca-d44cba9c268e	d3e8bb4a-d6e2-49d5-80b9-ce47d1d2af92	6793ba9e-25be-4436-960e-370a0ed6c013	2026-02-25 17:47:04.146455	\N
e8183343-082b-454e-95a9-38d09913418c	d3e8bb4a-d6e2-49d5-80b9-ce47d1d2af92	52b3e485-e445-406e-8d6d-c5c3b55361f4	2026-02-25 17:47:04.147453	\N
b1a86cb5-706c-48f7-b7f0-a49bfca2d3db	d3e8bb4a-d6e2-49d5-80b9-ce47d1d2af92	b6e6307e-3b55-4794-bc7e-1f793192a75d	2026-02-25 17:47:04.148451	\N
83fa09e6-0588-4a76-8a92-cc2e09b7dae1	d3e8bb4a-d6e2-49d5-80b9-ce47d1d2af92	e2bf1c97-a00b-4afa-a9c5-8e0e08d59f5a	2026-02-25 17:47:04.150448	\N
8f3e9707-dc8f-4825-9954-626c6b212289	d3e8bb4a-d6e2-49d5-80b9-ce47d1d2af92	5626f997-f5c0-410a-af8b-39add82f8cec	2026-02-25 17:47:04.15145	\N
d639ba9f-dcb2-4995-80c2-e82bfbeafc1e	d4670a58-1d8a-4ced-966b-e32ed9b37037	5805e19e-c3e7-4086-bd7a-6a963539ef5e	2026-02-25 17:47:04.15345	\N
ff2c7578-f18a-4918-8d15-5863d7cbd9d9	d4670a58-1d8a-4ced-966b-e32ed9b37037	8662b74a-6abe-45a5-b2c7-98f621d8320a	2026-02-25 17:47:04.154452	\N
67300fb4-3a8d-4ad9-81c4-789e79fd0604	d4670a58-1d8a-4ced-966b-e32ed9b37037	7ad1f933-1522-497b-b668-765a416f9d04	2026-02-25 17:47:04.155451	\N
001af98b-094f-4fed-823d-0b3cb26d859c	d4670a58-1d8a-4ced-966b-e32ed9b37037	6793ba9e-25be-4436-960e-370a0ed6c013	2026-02-25 17:47:04.157449	\N
2bb2c50c-5aff-40ed-a049-88a1a4aa7bdd	d4670a58-1d8a-4ced-966b-e32ed9b37037	52b3e485-e445-406e-8d6d-c5c3b55361f4	2026-02-25 17:47:04.15845	\N
cc817a92-9e4b-4243-a10c-fef684a44244	d4670a58-1d8a-4ced-966b-e32ed9b37037	b6e6307e-3b55-4794-bc7e-1f793192a75d	2026-02-25 17:47:04.159451	\N
147551a9-3bf1-402d-ac1f-597783cec86b	d4670a58-1d8a-4ced-966b-e32ed9b37037	e2bf1c97-a00b-4afa-a9c5-8e0e08d59f5a	2026-02-25 17:47:04.160451	\N
f5a380e1-b946-42af-8b30-36cd8d71701d	d4670a58-1d8a-4ced-966b-e32ed9b37037	5626f997-f5c0-410a-af8b-39add82f8cec	2026-02-25 17:47:04.162469	\N
eda4300c-0dba-4676-8b8e-9613984868fc	63ad1a14-2623-4287-9dbf-dae8429c667f	9cadd170-eaf6-49fe-9504-2afc8766a6b2	2026-02-25 18:47:58.675962	0bc9c5f7-dc77-4f7d-bfbf-4b347a934b24
9972467f-d6b7-46db-8974-de41329ea7df	63ad1a14-2623-4287-9dbf-dae8429c667f	619b5ea4-4839-40ff-88c2-05c940ff3b15	2026-02-25 18:47:58.675962	0bc9c5f7-dc77-4f7d-bfbf-4b347a934b24
7c967f74-f43d-4963-85d9-d64d58581e07	63ad1a14-2623-4287-9dbf-dae8429c667f	5805e19e-c3e7-4086-bd7a-6a963539ef5e	2026-02-25 18:47:58.675962	0bc9c5f7-dc77-4f7d-bfbf-4b347a934b24
d728d97e-b7fb-4745-9fd0-4ebf7d6885d9	63ad1a14-2623-4287-9dbf-dae8429c667f	ee39bc5a-aad7-43ad-8294-04e88f982e56	2026-02-25 18:47:58.675962	0bc9c5f7-dc77-4f7d-bfbf-4b347a934b24
2a8b97c2-84aa-4f8d-8d0a-1805beb0490f	63ad1a14-2623-4287-9dbf-dae8429c667f	6793ba9e-25be-4436-960e-370a0ed6c013	2026-02-25 18:47:58.675962	0bc9c5f7-dc77-4f7d-bfbf-4b347a934b24
1125d3b1-cea9-43f2-b0d5-12f4fc89bb74	63ad1a14-2623-4287-9dbf-dae8429c667f	4c4efc0f-d514-47c6-b4fe-708c6b8e9f9c	2026-02-25 18:47:58.675962	0bc9c5f7-dc77-4f7d-bfbf-4b347a934b24
8501c486-35c6-4419-b27f-d5cae781c0ea	63ad1a14-2623-4287-9dbf-dae8429c667f	e63b6f2e-78dc-479c-904e-9f22f9b7b21a	2026-02-25 18:47:58.675962	0bc9c5f7-dc77-4f7d-bfbf-4b347a934b24
a7bb052d-438f-466c-9a19-5fc25edc8f3c	63ad1a14-2623-4287-9dbf-dae8429c667f	ae04fb5d-e4ef-4173-91ec-168aa812c17f	2026-02-25 18:47:58.675962	0bc9c5f7-dc77-4f7d-bfbf-4b347a934b24
de2c8ea8-c6de-4605-bdff-9d42d1e2dd11	63ad1a14-2623-4287-9dbf-dae8429c667f	5908338f-ddd4-4683-ac52-f8d7ceb897a1	2026-02-25 18:47:58.675962	0bc9c5f7-dc77-4f7d-bfbf-4b347a934b24
7f9156b3-fae3-48fe-99e3-76ad780ccb41	63ad1a14-2623-4287-9dbf-dae8429c667f	e3a66a83-0fc3-4973-848d-e0a23de86a52	2026-02-25 18:47:58.675962	0bc9c5f7-dc77-4f7d-bfbf-4b347a934b24
f87d69c8-1cc4-4eff-b403-50d0f04fe9e8	63ad1a14-2623-4287-9dbf-dae8429c667f	9933b355-d93d-4bed-87d8-3595fc72ee00	2026-02-25 18:47:58.675962	0bc9c5f7-dc77-4f7d-bfbf-4b347a934b24
13839432-42f4-44b1-ae01-9228b26b3de4	63ad1a14-2623-4287-9dbf-dae8429c667f	f05b272c-dfee-4354-a289-4762787789da	2026-02-25 18:47:58.675962	0bc9c5f7-dc77-4f7d-bfbf-4b347a934b24
da184694-7937-4010-8554-139216f10fa2	63ad1a14-2623-4287-9dbf-dae8429c667f	898e3a3b-54e7-49a4-adff-a02e09a04800	2026-02-25 18:47:58.675962	0bc9c5f7-dc77-4f7d-bfbf-4b347a934b24
bd71e486-60a7-41d4-8eaf-4f8dc3063306	63ad1a14-2623-4287-9dbf-dae8429c667f	7bd2845d-95e6-4d84-8c40-404910e7a352	2026-02-25 18:47:58.675962	0bc9c5f7-dc77-4f7d-bfbf-4b347a934b24
0619fcfe-7ee0-43f1-8e09-eef80c2cbbc6	63ad1a14-2623-4287-9dbf-dae8429c667f	0ec6ee5f-2ffa-4dda-9fc4-3162eb855547	2026-02-25 18:47:58.675962	0bc9c5f7-dc77-4f7d-bfbf-4b347a934b24
662bf852-084c-45fe-ad7b-dd8b0026db83	63ad1a14-2623-4287-9dbf-dae8429c667f	c1f876b7-82be-4652-b49e-e29f93418adf	2026-02-25 18:47:58.675962	0bc9c5f7-dc77-4f7d-bfbf-4b347a934b24
caae283b-b97a-42d4-9a9a-cbb46b619865	63ad1a14-2623-4287-9dbf-dae8429c667f	a10cceed-9994-40f9-97f8-b85da58309c9	2026-02-25 18:47:58.675962	0bc9c5f7-dc77-4f7d-bfbf-4b347a934b24
db5a9c91-4150-4429-84e1-4be210d1834e	63ad1a14-2623-4287-9dbf-dae8429c667f	88bb13ee-b611-44ae-a58e-94e70243b896	2026-02-25 18:47:58.675962	0bc9c5f7-dc77-4f7d-bfbf-4b347a934b24
516ad4fa-5341-44bb-9f9a-702c69c42f32	63ad1a14-2623-4287-9dbf-dae8429c667f	50303ba1-ca2c-491d-81b8-8b95e436c9da	2026-02-25 18:47:58.675962	0bc9c5f7-dc77-4f7d-bfbf-4b347a934b24
4c907e92-5e0e-41ee-9875-44bc6864cc1e	63ad1a14-2623-4287-9dbf-dae8429c667f	b6e6307e-3b55-4794-bc7e-1f793192a75d	2026-02-25 18:47:58.675962	0bc9c5f7-dc77-4f7d-bfbf-4b347a934b24
1fc2f46d-c570-42c1-a90f-ae0fb5287dfb	63ad1a14-2623-4287-9dbf-dae8429c667f	e01b31b8-f5c2-4b3d-8eae-b35eb12bc268	2026-02-25 18:47:58.675962	0bc9c5f7-dc77-4f7d-bfbf-4b347a934b24
0ec9ee8e-7334-4ebb-a301-05d234a839c1	63ad1a14-2623-4287-9dbf-dae8429c667f	7ad1f933-1522-497b-b668-765a416f9d04	2026-02-25 18:47:58.675962	0bc9c5f7-dc77-4f7d-bfbf-4b347a934b24
10cebfa8-0ca6-474b-b5e6-349ea1aeeb56	63ad1a14-2623-4287-9dbf-dae8429c667f	3374bf53-16bd-47f2-91b5-f8190f38554b	2026-02-25 18:47:58.675962	0bc9c5f7-dc77-4f7d-bfbf-4b347a934b24
b71f360d-a05e-4e13-8ffa-3be851118e7f	63ad1a14-2623-4287-9dbf-dae8429c667f	2511d363-1467-4683-9fb7-aec385271e03	2026-02-25 18:47:58.675962	0bc9c5f7-dc77-4f7d-bfbf-4b347a934b24
b3ad9553-e0cd-43de-9e5e-d8bcb1c0df65	63ad1a14-2623-4287-9dbf-dae8429c667f	035ce5bf-b2e0-42af-aa22-b5c221e6d640	2026-02-25 18:47:58.675962	0bc9c5f7-dc77-4f7d-bfbf-4b347a934b24
a260884f-2b09-476f-bdc8-44ec4d3ea035	63ad1a14-2623-4287-9dbf-dae8429c667f	bb580d29-f140-4664-9f9d-61459971cd91	2026-02-25 18:47:58.675962	0bc9c5f7-dc77-4f7d-bfbf-4b347a934b24
8a4e0668-0174-48e9-ac61-8f6aa63bd547	63ad1a14-2623-4287-9dbf-dae8429c667f	8662b74a-6abe-45a5-b2c7-98f621d8320a	2026-02-25 18:47:58.675962	0bc9c5f7-dc77-4f7d-bfbf-4b347a934b24
94081b0b-18f1-43f9-abdb-3d79b92214e8	63ad1a14-2623-4287-9dbf-dae8429c667f	09070d89-9465-4210-80ab-631cb7589e80	2026-02-25 18:47:58.675962	0bc9c5f7-dc77-4f7d-bfbf-4b347a934b24
caac4860-2499-46e4-8354-871c79004ac2	63ad1a14-2623-4287-9dbf-dae8429c667f	e8d71861-f149-4110-ad02-a12e9f74f62f	2026-02-25 18:47:58.675962	0bc9c5f7-dc77-4f7d-bfbf-4b347a934b24
ef0e7bec-6ada-405e-8295-4a6dc4f955b4	63ad1a14-2623-4287-9dbf-dae8429c667f	c060adfa-d126-4366-8b59-f557cdb6f908	2026-02-25 18:47:58.675962	0bc9c5f7-dc77-4f7d-bfbf-4b347a934b24
934eb43e-5cf2-4dea-8b70-8fb9984a2eef	63ad1a14-2623-4287-9dbf-dae8429c667f	bdf67ee9-71ba-4892-b499-4cf048c3f0fc	2026-02-25 18:47:58.675962	0bc9c5f7-dc77-4f7d-bfbf-4b347a934b24
3691cdf7-c6b3-4deb-ba87-ebccaf19a5fb	63ad1a14-2623-4287-9dbf-dae8429c667f	5feb4705-3e15-41f0-abe9-54a687cb8378	2026-02-25 18:47:58.675962	0bc9c5f7-dc77-4f7d-bfbf-4b347a934b24
443ed22f-6bdb-415d-bcfe-7d79c304e9e3	63ad1a14-2623-4287-9dbf-dae8429c667f	afcd3a39-93d8-4328-9b41-54dc3243551c	2026-02-25 18:47:58.675962	0bc9c5f7-dc77-4f7d-bfbf-4b347a934b24
fa458ad0-ec4e-4e79-a587-e34a3879e30a	63ad1a14-2623-4287-9dbf-dae8429c667f	52b3e485-e445-406e-8d6d-c5c3b55361f4	2026-02-25 18:47:58.675962	0bc9c5f7-dc77-4f7d-bfbf-4b347a934b24
d08651d0-8197-4984-803a-8f893ccc5f2b	63ad1a14-2623-4287-9dbf-dae8429c667f	9f58c27a-2443-463e-85af-49edfc2e5e7c	2026-02-25 18:47:58.675962	0bc9c5f7-dc77-4f7d-bfbf-4b347a934b24
72291885-2469-4403-89a2-b7d41a43a078	63ad1a14-2623-4287-9dbf-dae8429c667f	27178daf-3255-41e6-bb32-8f408d49bd9d	2026-02-25 18:47:58.675962	0bc9c5f7-dc77-4f7d-bfbf-4b347a934b24
4f2b0a75-5e60-4d31-ba8c-3745128d36a5	63ad1a14-2623-4287-9dbf-dae8429c667f	6d83db88-d70b-49c9-8b98-ad617f49a24f	2026-02-25 18:47:58.675962	0bc9c5f7-dc77-4f7d-bfbf-4b347a934b24
598342ad-2d5a-4a5e-aba3-f4f4e989bab2	63ad1a14-2623-4287-9dbf-dae8429c667f	82ad46cb-092f-4487-b272-2daf5541c897	2026-02-25 18:47:58.675962	0bc9c5f7-dc77-4f7d-bfbf-4b347a934b24
3c42fc9c-74da-4b30-b98a-1b6f1966a4ed	63ad1a14-2623-4287-9dbf-dae8429c667f	aa5381b9-60f0-4cea-8c5f-2274e56a654b	2026-02-25 18:47:58.675962	0bc9c5f7-dc77-4f7d-bfbf-4b347a934b24
6e2b702b-b44a-4348-9530-3246a06bf108	63ad1a14-2623-4287-9dbf-dae8429c667f	97ba4968-c723-4599-9615-849f6da31eae	2026-02-25 18:47:58.675962	0bc9c5f7-dc77-4f7d-bfbf-4b347a934b24
5b71b2b9-5ebf-4fcd-b091-8f4bbe2ef8fa	63ad1a14-2623-4287-9dbf-dae8429c667f	594f4900-5252-4a91-a462-707052a4c5d9	2026-02-25 18:47:58.675962	0bc9c5f7-dc77-4f7d-bfbf-4b347a934b24
d170a80d-e8d9-424b-8732-7daf61c77665	63ad1a14-2623-4287-9dbf-dae8429c667f	e2bf1c97-a00b-4afa-a9c5-8e0e08d59f5a	2026-02-25 18:47:58.675962	0bc9c5f7-dc77-4f7d-bfbf-4b347a934b24
658b1989-c365-4acc-947d-7dac3a111c80	63ad1a14-2623-4287-9dbf-dae8429c667f	fc27a1d1-6ef5-484e-b32b-47f5f3d7e81c	2026-02-25 18:47:58.675962	0bc9c5f7-dc77-4f7d-bfbf-4b347a934b24
7572a873-8e11-414e-839c-cfb79141b6fd	63ad1a14-2623-4287-9dbf-dae8429c667f	a429e651-676d-470a-b78e-72387bd23921	2026-02-25 18:47:58.675962	0bc9c5f7-dc77-4f7d-bfbf-4b347a934b24
c5e9b128-9d13-4963-b46c-d9ed0dade1cb	63ad1a14-2623-4287-9dbf-dae8429c667f	3a295541-7916-4fb6-ba4c-4b0512d70c84	2026-02-25 18:47:58.675962	0bc9c5f7-dc77-4f7d-bfbf-4b347a934b24
120818a5-549f-46ff-94cf-9c0a84c84aee	63ad1a14-2623-4287-9dbf-dae8429c667f	5626f997-f5c0-410a-af8b-39add82f8cec	2026-02-25 18:47:58.675962	0bc9c5f7-dc77-4f7d-bfbf-4b347a934b24
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
\.


--
-- Data for Name: security_components; Type: TABLE DATA; Schema: public; Owner: postgres
--

COPY public.security_components (component_id, component_code, component_name, component_type, description, is_enabled, config_json, priority, status, last_check_at, error_message, created_at, updated_at, created_by, updated_by) FROM stdin;
e3008c90-a916-4ea0-8864-a80558a511b7	rate_limiting	速率限制	middleware	API 请求速率限制，防止暴力攻击和资源滥用	t	{"burst": 20, "by_ip": true, "requests_per_minute": 100}	80	active	2026-02-25 10:04:26.172693	\N	2026-02-25 09:36:19.421277	2026-02-25 10:04:26.17048	\N	\N
ace80f1b-a88e-4e80-b195-9105eb9f8685	key_management	密钥管理机制	service	集中管理系统密钥，支持密钥轮换和版本控制	t	{"key_versions": 3, "rotation_days": 90, "rotation_enabled": false}	70	active	2026-02-25 10:04:26.177696	\N	2026-02-25 09:36:19.421277	2026-02-25 10:04:26.177269	\N	\N
9f351a68-4ca1-4668-abf0-02acdbefa6cb	input_validation	Pydantic 输入验证	service	使用 Pydantic 进行请求数据验证和类型检查	t	{"strict_mode": true, "validate_assignment": true}	75	active	2026-02-25 10:04:26.183693	\N	2026-02-25 09:36:19.421277	2026-02-25 10:04:26.181812	\N	\N
0026291b-75be-4dd1-8e0d-b5b980e83abd	bcrypt_hash	密码 Bcrypt 哈希	service	使用 bcrypt 算法对用户密码进行安全哈希存储	t	{"rounds": 12, "salt_rounds": 12}	95	active	2026-02-25 10:04:26.738004	\N	2026-02-25 09:36:19.421277	2026-02-25 10:04:26.188237	\N	\N
4efa5b2b-ce63-44e3-9da4-92dad80fcd97	jwt_auth	JWT Token 认证	middleware	JSON Web Token 身份认证机制，用于API请求的用户身份验证	t	{"algorithm": "HS256", "expire_minutes": 30, "refresh_expire_days": 7}	100	active	2026-02-25 10:04:26.744033	\N	2026-02-25 09:36:19.421277	2026-02-25 10:04:26.743303	\N	\N
4c209434-83ec-4af7-b927-103af35b260d	api_key_encryption	API 密钥加密存储	service	对交易所 API 密钥进行加密存储，使用 AES-256 加密算法	t	{"algorithm": "AES-256-GCM", "key_rotation_days": 90}	90	active	2026-02-25 10:04:26.748348	\N	2026-02-25 09:36:19.421277	2026-02-25 10:04:26.747903	\N	\N
474bc7dd-9dd6-4c9d-b98e-ae73c317659f	cors_protection	CORS 跨域保护	middleware	限制跨域请求来源，防止未授权的跨域访问	t	{"max_age": 3600, "allowed_origins": ["http://localhost:3000", "http://13.115.21.77:3000"], "allow_credentials": true}	85	active	2026-02-25 10:04:26.751349	\N	2026-02-25 09:36:19.421277	2026-02-25 10:04:26.751717	\N	\N
91aeec05-0717-4e31-9f39-913b8d2e0fe2	sql_audit	SQL 查询安全审计	protection	审计和监控 SQL 查询，防止 SQL 注入攻击	t	{"log_queries": false, "alert_threshold": 5, "detect_injection": true}	65	active	2026-02-25 10:12:20.34467	\N	2026-02-25 09:36:19.421277	2026-02-25 10:12:20.342372	\N	\N
8a34b422-3575-4408-9b16-793ecae5e1ee	csrf_protection	CSRF 跨站请求伪造保护	middleware	防止跨站请求伪造攻击，验证请求来源	t	{"token_length": 32, "cookie_secure": true, "expire_minutes": 60}	60	active	2026-02-25 10:12:26.735967	\N	2026-02-25 09:36:19.421277	2026-02-25 10:12:26.741757	\N	\N
0b0e7243-901d-4014-b4ce-a17583da7a62	websocket_auth	WebSocket 连接认证	middleware	WebSocket 连接的身份验证和授权机制	t	{"require_token": true, "heartbeat_interval": 30, "max_connections_per_user": 5}	55	active	2026-02-25 10:12:30.258529	\N	2026-02-25 09:36:19.421277	2026-02-25 10:12:30.270124	\N	\N
662c851f-7cf8-4c54-bc20-e1bbe8113977	request_signing	请求签名验证	middleware	API 请求签名机制，防止请求篡改和重放攻击	t	{"algorithm": "HMAC-SHA256", "nonce_required": true, "timestamp_tolerance": 300}	50	active	2026-02-25 10:12:33.470685	\N	2026-02-25 09:36:19.421277	2026-02-25 10:12:33.481979	\N	\N
6cbfa72b-f621-4bee-bd5a-563b30b53716	log_sanitization	日志脱敏处理	service	自动脱敏日志中的敏感信息（密码、密钥、个人信息等）	t	{"mask_char": "*", "mask_patterns": ["password", "api_key", "secret", "token"]}	45	active	2026-02-25 10:12:40.079634	\N	2026-02-25 09:36:19.421277	2026-02-25 10:12:40.086307	\N	\N
b5bae439-dfa7-470a-8840-ab75a5bc2b4c	ip_whitelist	IP 白名单控制	protection	限制只允许白名单内的 IP 地址访问敏感接口	f	{"whitelist": [], "block_mode": "deny", "enabled_paths": ["/api/v1/admin/*"]}	40	inactive	\N	\N	2026-02-25 09:36:19.421277	2026-02-25 09:36:40.067123	\N	\N
37fb118e-016d-4022-82ea-27c5ec9f0c93	backup_recovery	数据备份恢复	service	自动备份数据库和关键配置文件，支持快速恢复	f	{"encrypt_backup": true, "retention_days": 30, "backup_location": "/backups", "backup_interval_hours": 24}	25	inactive	\N	\N	2026-02-25 09:36:19.421277	2026-02-25 09:36:40.067123	\N	\N
bb09d622-5843-49e4-8a7f-3797d01d5435	secret_key_rotation	SECRET_KEY 轮换	service	定期更换系统 SECRET_KEY，增强安全性	f	{"key_strength": 256, "current_key_age_days": 0, "rotation_interval_days": 90}	20	inactive	\N	\N	2026-02-25 09:36:19.421277	2026-02-25 09:36:40.067123	\N	\N
816e9640-a453-4586-b822-4db30e4700e5	dependency_scan	依赖安全扫描	service	定期扫描项目依赖的安全漏洞	t	{"auto_update": false, "scan_interval_days": 7, "alert_on_vulnerability": true}	30	active	2026-02-25 10:12:47.132093	\N	2026-02-25 09:36:19.421277	2026-02-25 10:12:47.137093	\N	\N
5db2e69a-db39-4e6c-98fa-e4f0ee361c19	request_tracking	请求追踪系统	middleware	为每个请求生成唯一 ID，追踪请求链路和性能	t	{"header_name": "X-Request-ID", "log_requests": true, "track_performance": true}	35	active	2026-02-25 10:12:52.128831	\N	2026-02-25 09:36:19.421277	2026-02-25 10:12:52.134295	\N	\N
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
\.


--
-- Data for Name: strategies; Type: TABLE DATA; Schema: public; Owner: postgres
--

COPY public.strategies (id, user_id, name, symbol, direction, min_spread, status, params, created_at, updated_at) FROM stdin;
\.


--
-- Data for Name: strategy_configs; Type: TABLE DATA; Schema: public; Owner: postgres
--

COPY public.strategy_configs (config_id, user_id, strategy_type, target_spread, order_qty, retry_times, mt5_stuck_threshold, is_enabled, create_time, update_time, opening_sync_count, closing_sync_count, m_coin, ladders, opening_m_coin, closing_m_coin) FROM stdin;
3e47594b-2836-460a-9f9f-bde1f79efa9b	66764cd6-d1c9-4468-a478-85b526a16927	reverse	2650	0.1	2	5	t	2026-02-20 16:40:51.243939	2026-02-20 16:40:51.243939	3	3	5	[]	5	5
aa0ba1ff-ae2c-4df6-bbf9-a42442bccac5	0bc9c5f7-dc77-4f7d-bfbf-4b347a934b24	reverse	1	1	3	5	f	2026-02-26 11:19:02.659948	2026-02-28 17:46:13.301823	2	2	5	[{"enabled": true, "qtyLimit": 1.0, "openPrice": 2.3, "threshold": 0.0}]	1	1
a84bb13f-6861-42eb-be66-e35fb183b7a1	0bc9c5f7-dc77-4f7d-bfbf-4b347a934b24	forward	1	1	3	5	f	2026-02-22 16:40:03.849973	2026-02-28 17:46:51.533427	6	3	5	[{"enabled": true, "qtyLimit": 1.0, "openPrice": 2.0, "threshold": 2.0}]	1	1
\.


--
-- Data for Name: strategy_performance; Type: TABLE DATA; Schema: public; Owner: postgres
--

COPY public.strategy_performance (performance_id, strategy_id, today_trades, today_profit, total_trades, total_profit, win_rate, max_drawdown, date, "timestamp") FROM stdin;
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
-- Data for Name: trades; Type: TABLE DATA; Schema: public; Owner: postgres
--

COPY public.trades (trade_id, user_id, account_id, position_id, symbol, platform, side, trade_type, price, quantity, fee, realized_pnl, "timestamp", created_at) FROM stdin;
\.


--
-- Data for Name: user_roles; Type: TABLE DATA; Schema: public; Owner: postgres
--

COPY public.user_roles (id, user_id, role_id, assigned_at, assigned_by, expires_at) FROM stdin;
3b39b4a1-1bd3-4990-a2ee-35ec4f2b7b93	0bc9c5f7-dc77-4f7d-bfbf-4b347a934b24	63ad1a14-2623-4287-9dbf-dae8429c667f	2026-02-25 11:40:25.787715	0bc9c5f7-dc77-4f7d-bfbf-4b347a934b24	\N
77c553d0-a6d2-4263-8924-a7c720934a8a	66764cd6-d1c9-4468-a478-85b526a16927	d3e8bb4a-d6e2-49d5-80b9-ce47d1d2af92	2026-02-25 11:40:37.897044	0bc9c5f7-dc77-4f7d-bfbf-4b347a934b24	\N
583dea02-144c-4a32-9f74-6732e3f207e3	debdebe2-076c-4601-a415-a8ad3ffd89e1	d3e8bb4a-d6e2-49d5-80b9-ce47d1d2af92	2026-02-25 11:40:44.33114	0bc9c5f7-dc77-4f7d-bfbf-4b347a934b24	\N
\.


--
-- Data for Name: users; Type: TABLE DATA; Schema: public; Owner: postgres
--

COPY public.users (user_id, username, password_hash, email, create_time, update_time, is_active, role) FROM stdin;
0bc9c5f7-dc77-4f7d-bfbf-4b347a934b24	admin	$2b$12$/m360CUn6D5yxJ1zOjZuxuYA.o23N73bspjWtSaSUsbcKyO2lVg0S	admin@hustle.com	2026-02-20 10:06:23.357013	2026-02-20 10:06:23.357013	t	管理员
66764cd6-d1c9-4468-a478-85b526a16927	cq987	$2b$12$gmrQ8HR7kSYvquCAK4yYJuCZ3KO9X2J9ZEF7MBADrij5b.3zHQ8c.	1@5.com	2026-02-20 13:28:05.250344	2026-02-20 13:28:05.250344	t	交易员
debdebe2-076c-4601-a415-a8ad3ffd89e1	no456	$2b$12$kWzbVDHMn45LaLQiZ0/Qxep1gSUSeYJ84rtWae973REmOF4rbJ7tK	1@6.com	2026-02-20 13:28:41.870101	2026-02-20 13:28:41.870101	t	交易员
\.


--
-- Data for Name: version_backups; Type: TABLE DATA; Schema: public; Owner: postgres
--

COPY public.version_backups (backup_id, backup_filename, "timestamp", description, status) FROM stdin;
\.


--
-- Name: platforms_platform_id_seq; Type: SEQUENCE SET; Schema: public; Owner: postgres
--

SELECT pg_catalog.setval('public.platforms_platform_id_seq', 1, false);


--
-- Name: strategies_id_seq; Type: SEQUENCE SET; Schema: public; Owner: postgres
--

SELECT pg_catalog.setval('public.strategies_id_seq', 1, false);


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
-- Name: market_data market_data_pkey; Type: CONSTRAINT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.market_data
    ADD CONSTRAINT market_data_pkey PRIMARY KEY (id);


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
-- Name: trades trades_pkey; Type: CONSTRAINT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.trades
    ADD CONSTRAINT trades_pkey PRIMARY KEY (trade_id);


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
-- Name: idx_user_roles_role; Type: INDEX; Schema: public; Owner: postgres
--

CREATE INDEX idx_user_roles_role ON public.user_roles USING btree (role_id);


--
-- Name: idx_user_roles_user; Type: INDEX; Schema: public; Owner: postgres
--

CREATE INDEX idx_user_roles_user ON public.user_roles USING btree (user_id);


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
-- PostgreSQL database dump complete
--

\unrestrict 3toF3YMs01ArngYvhSr8ZzeRtYIUEeABZkH2MgfXYl2aTDasm22hQGtoncoWqmU

