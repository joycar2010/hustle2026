--
-- PostgreSQL database dump
--

\restrict MWKwDyrs9TGgCqSggX18wf5A79ypOpAGQSrqwxKgmgwRMl7Mh0rxIB8EFhdQAqM

-- Dumped from database version 16.14 (Ubuntu 16.14-0ubuntu0.24.04.1)
-- Dumped by pg_dump version 16.14 (Ubuntu 16.14-0ubuntu0.24.04.1)

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
-- Name: trg_accounts_is_active_to_status(); Type: FUNCTION; Schema: public; Owner: postgres
--

CREATE FUNCTION public.trg_accounts_is_active_to_status() RETURNS trigger
    LANGUAGE plpgsql
    AS $$
BEGIN
  IF NEW.is_active IS DISTINCT FROM OLD.is_active THEN
    NEW.status := CASE WHEN NEW.is_active THEN 'active' ELSE 'disabled' END;
  END IF;
  RETURN NEW;
END;
$$;


ALTER FUNCTION public.trg_accounts_is_active_to_status() OWNER TO postgres;

--
-- Name: trg_accounts_status_to_is_active(); Type: FUNCTION; Schema: public; Owner: postgres
--

CREATE FUNCTION public.trg_accounts_status_to_is_active() RETURNS trigger
    LANGUAGE plpgsql
    AS $$
BEGIN
  IF NEW.status IS DISTINCT FROM OLD.status THEN
    NEW.is_active := (NEW.status = 'active');
  END IF;
  RETURN NEW;
END;
$$;


ALTER FUNCTION public.trg_accounts_status_to_is_active() OWNER TO postgres;

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
-- Name: account_proxy_bindings; Type: TABLE; Schema: public; Owner: postgres
--

CREATE TABLE public.account_proxy_bindings (
    id integer NOT NULL,
    account_id uuid NOT NULL,
    proxy_id integer NOT NULL,
    platform_id integer NOT NULL,
    is_active boolean DEFAULT true NOT NULL,
    priority integer DEFAULT 0 NOT NULL,
    bind_time timestamp without time zone DEFAULT now() NOT NULL,
    unbind_time timestamp without time zone,
    created_at timestamp without time zone DEFAULT now() NOT NULL,
    updated_at timestamp without time zone DEFAULT now() NOT NULL
);


ALTER TABLE public.account_proxy_bindings OWNER TO postgres;

--
-- Name: account_proxy_bindings_id_seq; Type: SEQUENCE; Schema: public; Owner: postgres
--

CREATE SEQUENCE public.account_proxy_bindings_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


ALTER SEQUENCE public.account_proxy_bindings_id_seq OWNER TO postgres;

--
-- Name: account_proxy_bindings_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: postgres
--

ALTER SEQUENCE public.account_proxy_bindings_id_seq OWNED BY public.account_proxy_bindings.id;


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
    proxy_config jsonb,
    account_role character varying(10),
    status character varying(20) DEFAULT 'active'::character varying NOT NULL,
    shard_config jsonb
);


ALTER TABLE public.accounts OWNER TO postgres;

--
-- Name: COLUMN accounts.proxy_config; Type: COMMENT; Schema: public; Owner: postgres
--

COMMENT ON COLUMN public.accounts.proxy_config IS 'IPIPGO静态IP代理配置';


--
-- Name: COLUMN accounts.shard_config; Type: COMMENT; Schema: public; Owner: postgres
--

COMMENT ON COLUMN public.accounts.shard_config IS 'Worker sharding configuration: {"mode": "include|exclude", "patterns": ["BTCUSDT", "ETH*"]}';


--
-- Name: agent_active_config; Type: TABLE; Schema: public; Owner: postgres
--

CREATE TABLE public.agent_active_config (
    key text NOT NULL,
    value jsonb NOT NULL,
    source_proposal_id bigint,
    updated_at timestamp with time zone DEFAULT now() NOT NULL,
    updated_by uuid
);


ALTER TABLE public.agent_active_config OWNER TO postgres;

--
-- Name: agent_alerts; Type: TABLE; Schema: public; Owner: postgres
--

CREATE TABLE public.agent_alerts (
    id bigint NOT NULL,
    created_at timestamp with time zone DEFAULT now() NOT NULL,
    level text NOT NULL,
    category text NOT NULL,
    message text NOT NULL,
    payload jsonb,
    feishu_sent boolean DEFAULT false,
    ack_required boolean DEFAULT false,
    ack_at timestamp with time zone,
    ack_by uuid,
    CONSTRAINT agent_alerts_level_check CHECK ((level = ANY (ARRAY['info'::text, 'warn'::text, 'danger'::text, 'critical'::text])))
);


ALTER TABLE public.agent_alerts OWNER TO postgres;

--
-- Name: agent_alerts_id_seq; Type: SEQUENCE; Schema: public; Owner: postgres
--

CREATE SEQUENCE public.agent_alerts_id_seq
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


ALTER SEQUENCE public.agent_alerts_id_seq OWNER TO postgres;

--
-- Name: agent_alerts_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: postgres
--

ALTER SEQUENCE public.agent_alerts_id_seq OWNED BY public.agent_alerts.id;


--
-- Name: agent_decisions_legacy; Type: TABLE; Schema: public; Owner: postgres
--

CREATE TABLE public.agent_decisions_legacy (
    id bigint NOT NULL,
    created_at timestamp with time zone DEFAULT now() NOT NULL,
    trigger text NOT NULL,
    market_snapshot jsonb NOT NULL,
    proposal jsonb NOT NULL,
    verdict text NOT NULL,
    reject_reason text,
    execution_result jsonb,
    llm_tokens_in integer,
    llm_tokens_out integer,
    llm_latency_ms integer,
    scope_user_id uuid,
    scope_pair_code character varying(30),
    scope_target_id integer,
    CONSTRAINT agent_decisions_verdict_check CHECK ((verdict = ANY (ARRAY['executed'::text, 'rejected'::text, 'shadow'::text, 'pending'::text])))
);


ALTER TABLE public.agent_decisions_legacy OWNER TO postgres;

--
-- Name: agent_decisions_legacy_id_seq; Type: SEQUENCE; Schema: public; Owner: postgres
--

CREATE SEQUENCE public.agent_decisions_legacy_id_seq
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


ALTER SEQUENCE public.agent_decisions_legacy_id_seq OWNER TO postgres;

--
-- Name: agent_decisions_legacy_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: postgres
--

ALTER SEQUENCE public.agent_decisions_legacy_id_seq OWNED BY public.agent_decisions_legacy.id;


--
-- Name: agent_decisions; Type: TABLE; Schema: public; Owner: postgres
--

CREATE TABLE public.agent_decisions (
    id bigint DEFAULT nextval('public.agent_decisions_legacy_id_seq'::regclass) NOT NULL,
    created_at timestamp with time zone DEFAULT now() NOT NULL,
    trigger text NOT NULL,
    market_snapshot jsonb NOT NULL,
    proposal jsonb NOT NULL,
    verdict text NOT NULL,
    reject_reason text,
    execution_result jsonb,
    llm_tokens_in integer,
    llm_tokens_out integer,
    llm_latency_ms integer,
    scope_user_id uuid,
    scope_pair_code character varying(30),
    scope_target_id integer,
    CONSTRAINT agent_decisions_verdict_check CHECK ((verdict = ANY (ARRAY['executed'::text, 'rejected'::text, 'shadow'::text, 'pending'::text])))
)
PARTITION BY RANGE (created_at);


ALTER TABLE public.agent_decisions OWNER TO postgres;

--
-- Name: agent_decisions_default; Type: TABLE; Schema: public; Owner: postgres
--

CREATE TABLE public.agent_decisions_default (
    id bigint DEFAULT nextval('public.agent_decisions_legacy_id_seq'::regclass) NOT NULL,
    created_at timestamp with time zone DEFAULT now() NOT NULL,
    trigger text NOT NULL,
    market_snapshot jsonb NOT NULL,
    proposal jsonb NOT NULL,
    verdict text NOT NULL,
    reject_reason text,
    execution_result jsonb,
    llm_tokens_in integer,
    llm_tokens_out integer,
    llm_latency_ms integer,
    scope_user_id uuid,
    scope_pair_code character varying(30),
    scope_target_id integer,
    CONSTRAINT agent_decisions_verdict_check CHECK ((verdict = ANY (ARRAY['executed'::text, 'rejected'::text, 'shadow'::text, 'pending'::text])))
);


ALTER TABLE public.agent_decisions_default OWNER TO postgres;

--
-- Name: agent_decisions_y2026m04; Type: TABLE; Schema: public; Owner: postgres
--

CREATE TABLE public.agent_decisions_y2026m04 (
    id bigint DEFAULT nextval('public.agent_decisions_legacy_id_seq'::regclass) NOT NULL,
    created_at timestamp with time zone DEFAULT now() NOT NULL,
    trigger text NOT NULL,
    market_snapshot jsonb NOT NULL,
    proposal jsonb NOT NULL,
    verdict text NOT NULL,
    reject_reason text,
    execution_result jsonb,
    llm_tokens_in integer,
    llm_tokens_out integer,
    llm_latency_ms integer,
    scope_user_id uuid,
    scope_pair_code character varying(30),
    scope_target_id integer,
    CONSTRAINT agent_decisions_verdict_check CHECK ((verdict = ANY (ARRAY['executed'::text, 'rejected'::text, 'shadow'::text, 'pending'::text])))
);


ALTER TABLE public.agent_decisions_y2026m04 OWNER TO postgres;

--
-- Name: agent_decisions_y2026m05; Type: TABLE; Schema: public; Owner: postgres
--

CREATE TABLE public.agent_decisions_y2026m05 (
    id bigint DEFAULT nextval('public.agent_decisions_legacy_id_seq'::regclass) NOT NULL,
    created_at timestamp with time zone DEFAULT now() NOT NULL,
    trigger text NOT NULL,
    market_snapshot jsonb NOT NULL,
    proposal jsonb NOT NULL,
    verdict text NOT NULL,
    reject_reason text,
    execution_result jsonb,
    llm_tokens_in integer,
    llm_tokens_out integer,
    llm_latency_ms integer,
    scope_user_id uuid,
    scope_pair_code character varying(30),
    scope_target_id integer,
    CONSTRAINT agent_decisions_verdict_check CHECK ((verdict = ANY (ARRAY['executed'::text, 'rejected'::text, 'shadow'::text, 'pending'::text])))
);


ALTER TABLE public.agent_decisions_y2026m05 OWNER TO postgres;

--
-- Name: agent_decisions_y2026m06; Type: TABLE; Schema: public; Owner: postgres
--

CREATE TABLE public.agent_decisions_y2026m06 (
    id bigint DEFAULT nextval('public.agent_decisions_legacy_id_seq'::regclass) NOT NULL,
    created_at timestamp with time zone DEFAULT now() NOT NULL,
    trigger text NOT NULL,
    market_snapshot jsonb NOT NULL,
    proposal jsonb NOT NULL,
    verdict text NOT NULL,
    reject_reason text,
    execution_result jsonb,
    llm_tokens_in integer,
    llm_tokens_out integer,
    llm_latency_ms integer,
    scope_user_id uuid,
    scope_pair_code character varying(30),
    scope_target_id integer,
    CONSTRAINT agent_decisions_verdict_check CHECK ((verdict = ANY (ARRAY['executed'::text, 'rejected'::text, 'shadow'::text, 'pending'::text])))
);


ALTER TABLE public.agent_decisions_y2026m06 OWNER TO postgres;

--
-- Name: agent_decisions_y2026m07; Type: TABLE; Schema: public; Owner: postgres
--

CREATE TABLE public.agent_decisions_y2026m07 (
    id bigint DEFAULT nextval('public.agent_decisions_legacy_id_seq'::regclass) NOT NULL,
    created_at timestamp with time zone DEFAULT now() NOT NULL,
    trigger text NOT NULL,
    market_snapshot jsonb NOT NULL,
    proposal jsonb NOT NULL,
    verdict text NOT NULL,
    reject_reason text,
    execution_result jsonb,
    llm_tokens_in integer,
    llm_tokens_out integer,
    llm_latency_ms integer,
    scope_user_id uuid,
    scope_pair_code character varying(30),
    scope_target_id integer,
    CONSTRAINT agent_decisions_verdict_check CHECK ((verdict = ANY (ARRAY['executed'::text, 'rejected'::text, 'shadow'::text, 'pending'::text])))
);


ALTER TABLE public.agent_decisions_y2026m07 OWNER TO postgres;

--
-- Name: agent_decisions_y2026m08; Type: TABLE; Schema: public; Owner: postgres
--

CREATE TABLE public.agent_decisions_y2026m08 (
    id bigint DEFAULT nextval('public.agent_decisions_legacy_id_seq'::regclass) NOT NULL,
    created_at timestamp with time zone DEFAULT now() NOT NULL,
    trigger text NOT NULL,
    market_snapshot jsonb NOT NULL,
    proposal jsonb NOT NULL,
    verdict text NOT NULL,
    reject_reason text,
    execution_result jsonb,
    llm_tokens_in integer,
    llm_tokens_out integer,
    llm_latency_ms integer,
    scope_user_id uuid,
    scope_pair_code character varying(30),
    scope_target_id integer,
    CONSTRAINT agent_decisions_verdict_check CHECK ((verdict = ANY (ARRAY['executed'::text, 'rejected'::text, 'shadow'::text, 'pending'::text])))
);


ALTER TABLE public.agent_decisions_y2026m08 OWNER TO postgres;

--
-- Name: agent_decisions_y2026m09; Type: TABLE; Schema: public; Owner: postgres
--

CREATE TABLE public.agent_decisions_y2026m09 (
    id bigint DEFAULT nextval('public.agent_decisions_legacy_id_seq'::regclass) NOT NULL,
    created_at timestamp with time zone DEFAULT now() NOT NULL,
    trigger text NOT NULL,
    market_snapshot jsonb NOT NULL,
    proposal jsonb NOT NULL,
    verdict text NOT NULL,
    reject_reason text,
    execution_result jsonb,
    llm_tokens_in integer,
    llm_tokens_out integer,
    llm_latency_ms integer,
    scope_user_id uuid,
    scope_pair_code character varying(30),
    scope_target_id integer,
    CONSTRAINT agent_decisions_verdict_check CHECK ((verdict = ANY (ARRAY['executed'::text, 'rejected'::text, 'shadow'::text, 'pending'::text])))
);


ALTER TABLE public.agent_decisions_y2026m09 OWNER TO postgres;

--
-- Name: agent_proposal_audit; Type: TABLE; Schema: public; Owner: postgres
--

CREATE TABLE public.agent_proposal_audit (
    id bigint NOT NULL,
    proposal_id bigint NOT NULL,
    action text NOT NULL,
    actor_user_id uuid,
    reason text,
    diff_keys text[],
    target_id integer,
    created_at timestamp with time zone DEFAULT now() NOT NULL,
    CONSTRAINT agent_proposal_audit_action_check CHECK ((action = ANY (ARRAY['approved'::text, 'rejected'::text, 'created'::text, 'rolled_back'::text])))
);


ALTER TABLE public.agent_proposal_audit OWNER TO postgres;

--
-- Name: agent_proposal_audit_id_seq; Type: SEQUENCE; Schema: public; Owner: postgres
--

CREATE SEQUENCE public.agent_proposal_audit_id_seq
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


ALTER SEQUENCE public.agent_proposal_audit_id_seq OWNER TO postgres;

--
-- Name: agent_proposal_audit_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: postgres
--

ALTER SEQUENCE public.agent_proposal_audit_id_seq OWNED BY public.agent_proposal_audit.id;


--
-- Name: agent_proposals; Type: TABLE; Schema: public; Owner: postgres
--

CREATE TABLE public.agent_proposals (
    id integer NOT NULL,
    created_at timestamp with time zone DEFAULT now() NOT NULL,
    target_id integer,
    scope_user_id uuid,
    scope_pair_code character varying(20),
    title character varying(200),
    description text,
    config_diff jsonb,
    status character varying(20) DEFAULT 'pending'::character varying NOT NULL,
    reviewed_by uuid,
    reviewed_at timestamp with time zone,
    review_reason text,
    source_decision_id integer,
    proposal_snapshot jsonb,
    CONSTRAINT agent_proposals_status_check CHECK (((status)::text = ANY ((ARRAY['pending'::character varying, 'approved'::character varying, 'rejected'::character varying, 'rolled_back'::character varying])::text[])))
);


ALTER TABLE public.agent_proposals OWNER TO postgres;

--
-- Name: agent_proposals_id_seq; Type: SEQUENCE; Schema: public; Owner: postgres
--

CREATE SEQUENCE public.agent_proposals_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


ALTER SEQUENCE public.agent_proposals_id_seq OWNER TO postgres;

--
-- Name: agent_proposals_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: postgres
--

ALTER SEQUENCE public.agent_proposals_id_seq OWNED BY public.agent_proposals.id;


--
-- Name: agent_scope_targets; Type: TABLE; Schema: public; Owner: postgres
--

CREATE TABLE public.agent_scope_targets (
    id integer NOT NULL,
    user_id uuid NOT NULL,
    pair_code character varying(30) NOT NULL,
    enabled boolean DEFAULT true NOT NULL,
    priority integer DEFAULT 0 NOT NULL,
    created_at timestamp with time zone DEFAULT now() NOT NULL,
    updated_at timestamp with time zone DEFAULT now() NOT NULL
);


ALTER TABLE public.agent_scope_targets OWNER TO postgres;

--
-- Name: agent_scope_targets_id_seq; Type: SEQUENCE; Schema: public; Owner: postgres
--

CREATE SEQUENCE public.agent_scope_targets_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


ALTER SEQUENCE public.agent_scope_targets_id_seq OWNER TO postgres;

--
-- Name: agent_scope_targets_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: postgres
--

ALTER SEQUENCE public.agent_scope_targets_id_seq OWNED BY public.agent_scope_targets.id;


--
-- Name: agent_state; Type: TABLE; Schema: public; Owner: postgres
--

CREATE TABLE public.agent_state (
    id integer DEFAULT 1 NOT NULL,
    mode text DEFAULT 'shadow'::text NOT NULL,
    kill_switch boolean DEFAULT false NOT NULL,
    shadow_started_at timestamp with time zone,
    last_decision_at timestamp with time zone,
    config jsonb DEFAULT '{}'::jsonb NOT NULL,
    updated_at timestamp with time zone DEFAULT now() NOT NULL,
    openclaw_enabled boolean DEFAULT true NOT NULL,
    CONSTRAINT agent_state_id_check CHECK ((id = 1)),
    CONSTRAINT agent_state_mode_check CHECK ((mode = ANY (ARRAY['off'::text, 'shadow'::text, 'semi'::text, 'auto'::text])))
);


ALTER TABLE public.agent_state OWNER TO postgres;

--
-- Name: agent_strategy_proposals; Type: TABLE; Schema: public; Owner: postgres
--

CREATE TABLE public.agent_strategy_proposals (
    id bigint NOT NULL,
    created_at timestamp with time zone DEFAULT now() NOT NULL,
    title text NOT NULL,
    rationale text NOT NULL,
    config_diff jsonb NOT NULL,
    est_position_pct numeric,
    backtest_result jsonb,
    status text DEFAULT 'pending'::text NOT NULL,
    reviewed_by uuid,
    reviewed_at timestamp with time zone,
    activated_at timestamp with time zone,
    target_id integer,
    CONSTRAINT agent_strategy_proposals_status_check CHECK ((status = ANY (ARRAY['pending'::text, 'approved'::text, 'rejected'::text, 'rolled_back'::text])))
);


ALTER TABLE public.agent_strategy_proposals OWNER TO postgres;

--
-- Name: agent_strategy_proposals_id_seq; Type: SEQUENCE; Schema: public; Owner: postgres
--

CREATE SEQUENCE public.agent_strategy_proposals_id_seq
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


ALTER SEQUENCE public.agent_strategy_proposals_id_seq OWNER TO postgres;

--
-- Name: agent_strategy_proposals_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: postgres
--

ALTER SEQUENCE public.agent_strategy_proposals_id_seq OWNED BY public.agent_strategy_proposals.id;


--
-- Name: agent_target_config; Type: TABLE; Schema: public; Owner: postgres
--

CREATE TABLE public.agent_target_config (
    target_id integer NOT NULL,
    key text NOT NULL,
    value jsonb NOT NULL,
    source_proposal_id bigint,
    updated_at timestamp with time zone DEFAULT now() NOT NULL,
    updated_by uuid
);


ALTER TABLE public.agent_target_config OWNER TO postgres;

--
-- Name: ai_arb_analysis; Type: TABLE; Schema: public; Owner: postgres
--

CREATE TABLE public.ai_arb_analysis (
    id bigint NOT NULL,
    targets jsonb NOT NULL,
    window_h integer DEFAULT 24 NOT NULL,
    input_stats jsonb,
    analysis jsonb,
    model character varying(64),
    created_by uuid,
    created_at timestamp with time zone DEFAULT now() NOT NULL
);


ALTER TABLE public.ai_arb_analysis OWNER TO postgres;

--
-- Name: ai_arb_analysis_id_seq; Type: SEQUENCE; Schema: public; Owner: postgres
--

CREATE SEQUENCE public.ai_arb_analysis_id_seq
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


ALTER SEQUENCE public.ai_arb_analysis_id_seq OWNER TO postgres;

--
-- Name: ai_arb_analysis_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: postgres
--

ALTER SEQUENCE public.ai_arb_analysis_id_seq OWNED BY public.ai_arb_analysis.id;


--
-- Name: aicoin_config; Type: TABLE; Schema: public; Owner: postgres
--

CREATE TABLE public.aicoin_config (
    id integer NOT NULL,
    api_key character varying(200),
    api_secret character varying(500),
    api_base character varying(200) DEFAULT 'https://open.aicoin.com'::character varying,
    enabled boolean DEFAULT true,
    updated_at timestamp without time zone DEFAULT now(),
    updated_by character varying(100),
    expires_at timestamp without time zone
);


ALTER TABLE public.aicoin_config OWNER TO postgres;

--
-- Name: aicoin_config_id_seq; Type: SEQUENCE; Schema: public; Owner: postgres
--

CREATE SEQUENCE public.aicoin_config_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


ALTER SEQUENCE public.aicoin_config_id_seq OWNER TO postgres;

--
-- Name: aicoin_config_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: postgres
--

ALTER SEQUENCE public.aicoin_config_id_seq OWNED BY public.aicoin_config.id;


--
-- Name: alembic_version; Type: TABLE; Schema: public; Owner: postgres
--

CREATE TABLE public.alembic_version (
    version_num character varying(32) NOT NULL
);


ALTER TABLE public.alembic_version OWNER TO postgres;

--
-- Name: arbitrage_opportunities; Type: TABLE; Schema: public; Owner: postgres
--

CREATE TABLE public.arbitrage_opportunities (
    id uuid DEFAULT public.uuid_generate_v4() NOT NULL,
    symbol character varying(20) NOT NULL,
    binance_bid double precision NOT NULL,
    binance_ask double precision NOT NULL,
    bybit_bid double precision NOT NULL,
    bybit_ask double precision NOT NULL,
    forward_spread double precision NOT NULL,
    reverse_spread double precision NOT NULL,
    opportunity_type character varying(50) NOT NULL,
    target_spread double precision NOT NULL,
    "timestamp" timestamp without time zone NOT NULL,
    created_at timestamp without time zone DEFAULT now() NOT NULL
);


ALTER TABLE public.arbitrage_opportunities OWNER TO postgres;

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
-- Name: binance_income; Type: TABLE; Schema: public; Owner: postgres
--

CREATE TABLE public.binance_income (
    id bigint NOT NULL,
    account_id uuid NOT NULL,
    tran_id bigint,
    trade_id bigint,
    income_type character varying(32) NOT NULL,
    income numeric(30,12) NOT NULL,
    asset character varying(16),
    symbol character varying(32),
    income_time_ms bigint NOT NULL,
    info character varying(64),
    raw jsonb,
    created_at timestamp with time zone DEFAULT now() NOT NULL,
    dedup_key text GENERATED ALWAYS AS (COALESCE((tran_id)::text, (((((((((income_time_ms)::text || '|'::text) || (income_type)::text) || '|'::text) || (income)::text) || '|'::text) || (COALESCE(symbol, ''::character varying))::text) || '|'::text) || COALESCE((trade_id)::text, ''::text)))) STORED
);


ALTER TABLE public.binance_income OWNER TO postgres;

--
-- Name: binance_income_id_seq; Type: SEQUENCE; Schema: public; Owner: postgres
--

CREATE SEQUENCE public.binance_income_id_seq
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


ALTER SEQUENCE public.binance_income_id_seq OWNER TO postgres;

--
-- Name: binance_income_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: postgres
--

ALTER SEQUENCE public.binance_income_id_seq OWNED BY public.binance_income.id;


--
-- Name: equity_intervention_log; Type: TABLE; Schema: public; Owner: postgres
--

CREATE TABLE public.equity_intervention_log (
    id bigint NOT NULL,
    account_id uuid NOT NULL,
    state text NOT NULL,
    equity_ratio numeric,
    triggered_at timestamp with time zone DEFAULT now() NOT NULL,
    resolved_at timestamp with time zone,
    forced_reduce_pct numeric,
    ack_by uuid,
    details jsonb,
    scope_target_id integer,
    CONSTRAINT equity_intervention_log_state_check CHECK ((state = ANY (ARRAY['NORMAL'::text, 'WARNING'::text, 'ESCALATING'::text, 'FORCED_REDUCE'::text, 'RESOLVED'::text])))
);


ALTER TABLE public.equity_intervention_log OWNER TO postgres;

--
-- Name: equity_intervention_log_id_seq; Type: SEQUENCE; Schema: public; Owner: postgres
--

CREATE SEQUENCE public.equity_intervention_log_id_seq
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


ALTER SEQUENCE public.equity_intervention_log_id_seq OWNER TO postgres;

--
-- Name: equity_intervention_log_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: postgres
--

ALTER SEQUENCE public.equity_intervention_log_id_seq OWNED BY public.equity_intervention_log.id;


--
-- Name: hedge_batch_records; Type: TABLE; Schema: public; Owner: postgres
--

CREATE TABLE public.hedge_batch_records (
    id uuid NOT NULL,
    user_id uuid NOT NULL,
    pair_code character varying(30) NOT NULL,
    strategy_type character varying(20) NOT NULL,
    batch_no integer NOT NULL,
    order_time timestamp without time zone NOT NULL,
    hedge_price double precision NOT NULL,
    hedge_qty double precision NOT NULL,
    direction character varying(10) NOT NULL,
    status character varying(10) NOT NULL,
    closed_at timestamp without time zone,
    create_time timestamp without time zone NOT NULL
);


ALTER TABLE public.hedge_batch_records OWNER TO postgres;

--
-- Name: hedging_pairs; Type: TABLE; Schema: public; Owner: postgres
--

CREATE TABLE public.hedging_pairs (
    id uuid DEFAULT gen_random_uuid() NOT NULL,
    pair_name character varying(60) NOT NULL,
    pair_code character varying(30) NOT NULL,
    account_a_id uuid,
    symbol_a_id uuid NOT NULL,
    account_b_id uuid,
    symbol_b_id uuid NOT NULL,
    conversion_factor double precision DEFAULT 100.0 NOT NULL,
    usd_usdt_rate double precision DEFAULT 1.0 NOT NULL,
    usd_usdt_auto_sync boolean DEFAULT false,
    spread_mode character varying(20) DEFAULT 'absolute'::character varying NOT NULL,
    spread_precision integer DEFAULT 2 NOT NULL,
    default_spread_target double precision,
    max_position_value_usd double precision,
    min_hedgeable_qty_a double precision,
    min_hedgeable_qty_b double precision,
    is_active boolean DEFAULT true NOT NULL,
    sort_order integer DEFAULT 0,
    created_at timestamp without time zone DEFAULT now(),
    updated_at timestamp without time zone DEFAULT now()
);


ALTER TABLE public.hedging_pairs OWNER TO postgres;

--
-- Name: hustle_chat_messages; Type: TABLE; Schema: public; Owner: postgres
--

CREATE TABLE public.hustle_chat_messages (
    id integer NOT NULL,
    user_id uuid NOT NULL,
    site character varying(20) DEFAULT 'auto'::character varying NOT NULL,
    role character varying(20) NOT NULL,
    content text NOT NULL,
    created_at timestamp with time zone DEFAULT now()
);


ALTER TABLE public.hustle_chat_messages OWNER TO postgres;

--
-- Name: hustle_chat_messages_id_seq; Type: SEQUENCE; Schema: public; Owner: postgres
--

CREATE SEQUENCE public.hustle_chat_messages_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


ALTER SEQUENCE public.hustle_chat_messages_id_seq OWNER TO postgres;

--
-- Name: hustle_chat_messages_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: postgres
--

ALTER SEQUENCE public.hustle_chat_messages_id_seq OWNED BY public.hustle_chat_messages.id;


--
-- Name: ladder_advisor_config; Type: TABLE; Schema: public; Owner: postgres
--

CREATE TABLE public.ladder_advisor_config (
    id smallint DEFAULT 1 NOT NULL,
    mode character varying(16) DEFAULT 'shadow'::character varying NOT NULL,
    max_auto_pct numeric(5,2) DEFAULT 10.0 NOT NULL,
    cooldown_hours integer DEFAULT 24 NOT NULL,
    enabled boolean DEFAULT true NOT NULL,
    updated_at timestamp with time zone DEFAULT now() NOT NULL
);


ALTER TABLE public.ladder_advisor_config OWNER TO postgres;

--
-- Name: ladder_advisor_log; Type: TABLE; Schema: public; Owner: postgres
--

CREATE TABLE public.ladder_advisor_log (
    id bigint NOT NULL,
    user_id uuid NOT NULL,
    strategy_type character varying(20) NOT NULL,
    pair_code character varying(30) NOT NULL,
    mode character varying(16) NOT NULL,
    action character varying(16) NOT NULL,
    old_ladders jsonb,
    new_ladders jsonb,
    rationale text,
    spread_stats jsonb,
    pnl_before_7d numeric(20,8),
    pnl_after_24h numeric(20,8),
    outcome_at timestamp with time zone,
    created_at timestamp with time zone DEFAULT now() NOT NULL
);


ALTER TABLE public.ladder_advisor_log OWNER TO postgres;

--
-- Name: ladder_advisor_log_id_seq; Type: SEQUENCE; Schema: public; Owner: postgres
--

CREATE SEQUENCE public.ladder_advisor_log_id_seq
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


ALTER SEQUENCE public.ladder_advisor_log_id_seq OWNER TO postgres;

--
-- Name: ladder_advisor_log_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: postgres
--

ALTER SEQUENCE public.ladder_advisor_log_id_seq OWNED BY public.ladder_advisor_log.id;


--
-- Name: leg_imbalance_log; Type: TABLE; Schema: public; Owner: postgres
--

CREATE TABLE public.leg_imbalance_log (
    id bigint NOT NULL,
    detected_at timestamp with time zone DEFAULT now() NOT NULL,
    a_size numeric NOT NULL,
    b_size numeric NOT NULL,
    delta numeric NOT NULL,
    conversion_factor numeric,
    resolved_at timestamp with time zone,
    resolution text
);


ALTER TABLE public.leg_imbalance_log OWNER TO postgres;

--
-- Name: leg_imbalance_log_id_seq; Type: SEQUENCE; Schema: public; Owner: postgres
--

CREATE SEQUENCE public.leg_imbalance_log_id_seq
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


ALTER SEQUENCE public.leg_imbalance_log_id_seq OWNER TO postgres;

--
-- Name: leg_imbalance_log_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: postgres
--

ALTER SEQUENCE public.leg_imbalance_log_id_seq OWNED BY public.leg_imbalance_log.id;


--
-- Name: manual_ledger; Type: TABLE; Schema: public; Owner: postgres
--

CREATE TABLE public.manual_ledger (
    id bigint NOT NULL,
    user_id uuid NOT NULL,
    entry_date date NOT NULL,
    total_amount numeric(20,2) NOT NULL,
    daily_pnl numeric(20,2) DEFAULT 0 NOT NULL,
    is_baseline boolean DEFAULT false NOT NULL,
    note character varying(200),
    created_at timestamp with time zone DEFAULT now() NOT NULL,
    updated_at timestamp with time zone DEFAULT now() NOT NULL
);


ALTER TABLE public.manual_ledger OWNER TO postgres;

--
-- Name: manual_ledger_id_seq; Type: SEQUENCE; Schema: public; Owner: postgres
--

CREATE SEQUENCE public.manual_ledger_id_seq
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


ALTER SEQUENCE public.manual_ledger_id_seq OWNER TO postgres;

--
-- Name: manual_ledger_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: postgres
--

ALTER SEQUENCE public.manual_ledger_id_seq OWNED BY public.manual_ledger.id;


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
    bridge_service_port integer,
    mt5_path character varying(500),
    mt5_data_path character varying(500),
    role character varying(20) DEFAULT 'trading'::character varying,
    bridge_health_status character varying(20) DEFAULT 'unknown'::character varying NOT NULL
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
-- Name: mt5_config; Type: TABLE; Schema: public; Owner: postgres
--

CREATE TABLE public.mt5_config (
    key character varying(100) NOT NULL,
    value text NOT NULL,
    description character varying(500),
    updated_at timestamp without time zone DEFAULT now()
);


ALTER TABLE public.mt5_config OWNER TO postgres;

--
-- Name: mt5_deals; Type: TABLE; Schema: public; Owner: postgres
--

CREATE TABLE public.mt5_deals (
    id bigint NOT NULL,
    account_id uuid NOT NULL,
    ticket bigint NOT NULL,
    order_id bigint,
    symbol character varying(32),
    deal_type smallint,
    entry smallint,
    volume numeric(20,8),
    price numeric(20,8),
    profit numeric(20,8),
    swap numeric(20,8),
    commission numeric(20,8),
    comment character varying(128),
    deal_time_raw bigint NOT NULL,
    deal_time_utc timestamp with time zone NOT NULL,
    bridge_port integer,
    raw jsonb,
    ingested_at timestamp with time zone DEFAULT now() NOT NULL
);


ALTER TABLE public.mt5_deals OWNER TO postgres;

--
-- Name: mt5_deals_id_seq; Type: SEQUENCE; Schema: public; Owner: postgres
--

CREATE SEQUENCE public.mt5_deals_id_seq
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


ALTER SEQUENCE public.mt5_deals_id_seq OWNER TO postgres;

--
-- Name: mt5_deals_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: postgres
--

ALTER SEQUENCE public.mt5_deals_id_seq OWNED BY public.mt5_deals.id;


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
-- Name: notification_subscriptions; Type: TABLE; Schema: public; Owner: postgres
--

CREATE TABLE public.notification_subscriptions (
    subscription_id uuid DEFAULT gen_random_uuid() NOT NULL,
    subscriber_user_id uuid NOT NULL,
    trader_user_id uuid NOT NULL,
    template_id uuid NOT NULL,
    is_enabled boolean DEFAULT true,
    created_at timestamp without time zone DEFAULT now()
);


ALTER TABLE public.notification_subscriptions OWNER TO postgres;

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
    alert_sound_repeat integer DEFAULT 3,
    enable_marquee boolean DEFAULT false NOT NULL
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
-- Name: pair_rate_records; Type: TABLE; Schema: public; Owner: postgres
--

CREATE TABLE public.pair_rate_records (
    id bigint NOT NULL,
    pair_code character varying(20) NOT NULL,
    funding_rate double precision,
    mark_price double precision,
    long_swap_per_lot double precision,
    short_swap_per_lot double precision,
    "timestamp" timestamp without time zone DEFAULT (now() AT TIME ZONE 'utc'::text) NOT NULL
);


ALTER TABLE public.pair_rate_records OWNER TO postgres;

--
-- Name: pair_rate_records_id_seq; Type: SEQUENCE; Schema: public; Owner: postgres
--

CREATE SEQUENCE public.pair_rate_records_id_seq
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


ALTER SEQUENCE public.pair_rate_records_id_seq OWNER TO postgres;

--
-- Name: pair_rate_records_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: postgres
--

ALTER SEQUENCE public.pair_rate_records_id_seq OWNED BY public.pair_rate_records.id;


--
-- Name: parent_cashflow_events; Type: TABLE; Schema: public; Owner: postgres
--

CREATE TABLE public.parent_cashflow_events (
    id uuid DEFAULT gen_random_uuid() NOT NULL,
    parent_user_id uuid NOT NULL,
    direction character varying(10) NOT NULL,
    amount_usdt numeric(24,8) NOT NULL,
    total_assets_pre numeric(24,8) NOT NULL,
    total_assets_post numeric(24,8) NOT NULL,
    virtual_shares_pre numeric(24,8) NOT NULL,
    virtual_shares_post numeric(24,8) NOT NULL,
    nav_at_event numeric(24,8) NOT NULL,
    shares_delta numeric(24,8) NOT NULL,
    note text,
    created_by uuid,
    created_at timestamp with time zone DEFAULT now() NOT NULL,
    CONSTRAINT parent_cashflow_events_amount_usdt_check CHECK ((amount_usdt > (0)::numeric)),
    CONSTRAINT parent_cashflow_events_direction_check CHECK (((direction)::text = ANY ((ARRAY['deposit'::character varying, 'withdraw'::character varying])::text[])))
);


ALTER TABLE public.parent_cashflow_events OWNER TO postgres;

--
-- Name: parent_share_state; Type: TABLE; Schema: public; Owner: postgres
--

CREATE TABLE public.parent_share_state (
    parent_user_id uuid NOT NULL,
    virtual_shares numeric(24,8) DEFAULT 0 NOT NULL,
    bootstrap_total_assets numeric(24,8) DEFAULT 0 NOT NULL,
    created_at timestamp with time zone DEFAULT now() NOT NULL,
    updated_at timestamp with time zone DEFAULT now() NOT NULL
);


ALTER TABLE public.parent_share_state OWNER TO postgres;

--
-- Name: pending_orders; Type: TABLE; Schema: public; Owner: postgres
--

CREATE TABLE public.pending_orders (
    id integer NOT NULL,
    user_id uuid NOT NULL,
    strategy_type character varying(50) NOT NULL,
    platform character varying(20) NOT NULL,
    order_id character varying(100),
    symbol character varying(30) NOT NULL,
    side character varying(10) NOT NULL,
    quantity double precision NOT NULL,
    price double precision,
    order_type character varying(20) DEFAULT 'MARKET'::character varying NOT NULL,
    status character varying(20) DEFAULT 'PENDING'::character varying NOT NULL,
    filled_quantity double precision DEFAULT 0,
    created_at timestamp without time zone DEFAULT now() NOT NULL,
    updated_at timestamp without time zone DEFAULT now() NOT NULL,
    expires_at timestamp without time zone,
    extra_data jsonb
);


ALTER TABLE public.pending_orders OWNER TO postgres;

--
-- Name: pending_orders_id_seq; Type: SEQUENCE; Schema: public; Owner: postgres
--

CREATE SEQUENCE public.pending_orders_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


ALTER SEQUENCE public.pending_orders_id_seq OWNER TO postgres;

--
-- Name: pending_orders_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: postgres
--

ALTER SEQUENCE public.pending_orders_id_seq OWNED BY public.pending_orders.id;


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
-- Name: platform_symbols; Type: TABLE; Schema: public; Owner: postgres
--

CREATE TABLE public.platform_symbols (
    id uuid DEFAULT gen_random_uuid() NOT NULL,
    platform_id smallint NOT NULL,
    symbol character varying(30) NOT NULL,
    base_asset character varying(10) NOT NULL,
    quote_asset character varying(10) DEFAULT 'USDT'::character varying NOT NULL,
    contract_unit double precision DEFAULT 1.0 NOT NULL,
    qty_unit character varying(20) DEFAULT 'XAU'::character varying NOT NULL,
    qty_precision integer DEFAULT 0 NOT NULL,
    qty_step double precision DEFAULT 1.0 NOT NULL,
    min_qty double precision DEFAULT 1.0 NOT NULL,
    price_precision integer DEFAULT 2 NOT NULL,
    price_step double precision DEFAULT 0.01 NOT NULL,
    maker_fee_rate double precision DEFAULT 0.0002 NOT NULL,
    taker_fee_rate double precision DEFAULT 0.0005 NOT NULL,
    fee_type character varying(20) DEFAULT 'percentage'::character varying NOT NULL,
    fee_per_lot double precision DEFAULT 0.0 NOT NULL,
    margin_rate_initial double precision DEFAULT 0.01 NOT NULL,
    margin_rate_maintenance double precision DEFAULT 0.005 NOT NULL,
    funding_interval character varying(10),
    swap_type character varying(20),
    trading_hours jsonb,
    is_active boolean DEFAULT true NOT NULL,
    created_at timestamp without time zone DEFAULT now(),
    product_type character varying(20) DEFAULT 'perpetual'::character varying
);


ALTER TABLE public.platform_symbols OWNER TO postgres;

--
-- Name: platforms; Type: TABLE; Schema: public; Owner: postgres
--

CREATE TABLE public.platforms (
    platform_id smallint NOT NULL,
    platform_name character varying(20) NOT NULL,
    api_base_url character varying(100) NOT NULL,
    ws_base_url character varying(100) NOT NULL,
    account_api_type character varying(30) NOT NULL,
    market_api_type character varying(30) NOT NULL,
    display_name character varying(50) DEFAULT ''::character varying NOT NULL,
    platform_type character varying(10) DEFAULT 'cex'::character varying NOT NULL,
    auth_type character varying(40) DEFAULT 'hmac_sha256'::character varying NOT NULL,
    position_mode character varying(20) DEFAULT 'hedging'::character varying NOT NULL,
    maker_mechanism character varying(40) DEFAULT 'none'::character varying NOT NULL,
    default_tif character varying(10) DEFAULT 'GTC'::character varying NOT NULL,
    base_currency character varying(10) DEFAULT 'USDT'::character varying NOT NULL,
    requires_proxy boolean DEFAULT false,
    is_active boolean DEFAULT true NOT NULL,
    mt5_template_path character varying(500)
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
-- Name: pnl_sync_watermark; Type: TABLE; Schema: public; Owner: postgres
--

CREATE TABLE public.pnl_sync_watermark (
    account_id uuid NOT NULL,
    source character varying(32) NOT NULL,
    covered_from_ms bigint,
    covered_to_ms bigint,
    last_sync_at timestamp with time zone,
    last_error text,
    updated_at timestamp with time zone DEFAULT now() NOT NULL
);


ALTER TABLE public.pnl_sync_watermark OWNER TO postgres;

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
-- Name: proxies; Type: TABLE; Schema: public; Owner: postgres
--

CREATE TABLE public.proxies (
    proxy_id integer NOT NULL,
    user_id uuid NOT NULL,
    proxy_name character varying(100) NOT NULL,
    proxy_type character varying(20) DEFAULT 'http'::character varying NOT NULL,
    host character varying(255) NOT NULL,
    port integer NOT NULL,
    username character varying(100),
    password character varying(255),
    is_active boolean DEFAULT true,
    last_check_time timestamp without time zone,
    last_check_status character varying(20),
    latency_ms double precision,
    created_at timestamp without time zone DEFAULT now(),
    updated_at timestamp without time zone DEFAULT now()
);


ALTER TABLE public.proxies OWNER TO postgres;

--
-- Name: proxies_proxy_id_seq; Type: SEQUENCE; Schema: public; Owner: postgres
--

CREATE SEQUENCE public.proxies_proxy_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


ALTER SEQUENCE public.proxies_proxy_id_seq OWNER TO postgres;

--
-- Name: proxies_proxy_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: postgres
--

ALTER SEQUENCE public.proxies_proxy_id_seq OWNED BY public.proxies.proxy_id;


--
-- Name: proxy_health_logs; Type: TABLE; Schema: public; Owner: postgres
--

CREATE TABLE public.proxy_health_logs (
    id integer NOT NULL,
    proxy_id integer NOT NULL,
    check_time timestamp without time zone NOT NULL,
    is_success boolean NOT NULL,
    latency_ms double precision,
    error_message text,
    check_type character varying(50) DEFAULT 'auto'::character varying NOT NULL,
    target_url character varying(255),
    response_code integer
);


ALTER TABLE public.proxy_health_logs OWNER TO postgres;

--
-- Name: proxy_health_logs_id_seq; Type: SEQUENCE; Schema: public; Owner: postgres
--

CREATE SEQUENCE public.proxy_health_logs_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


ALTER SEQUENCE public.proxy_health_logs_id_seq OWNER TO postgres;

--
-- Name: proxy_health_logs_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: postgres
--

ALTER SEQUENCE public.proxy_health_logs_id_seq OWNED BY public.proxy_health_logs.id;


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
-- Name: proxy_usage_stats; Type: TABLE; Schema: public; Owner: postgres
--

CREATE TABLE public.proxy_usage_stats (
    id integer NOT NULL,
    proxy_id integer NOT NULL,
    account_id uuid NOT NULL,
    platform_id integer NOT NULL,
    date date NOT NULL,
    total_requests integer DEFAULT 0 NOT NULL,
    success_requests integer DEFAULT 0 NOT NULL,
    failed_requests integer DEFAULT 0 NOT NULL,
    avg_latency_ms double precision,
    total_data_mb double precision DEFAULT 0 NOT NULL,
    created_at timestamp without time zone DEFAULT now() NOT NULL,
    updated_at timestamp without time zone DEFAULT now() NOT NULL
);


ALTER TABLE public.proxy_usage_stats OWNER TO postgres;

--
-- Name: proxy_usage_stats_id_seq; Type: SEQUENCE; Schema: public; Owner: postgres
--

CREATE SEQUENCE public.proxy_usage_stats_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


ALTER SEQUENCE public.proxy_usage_stats_id_seq OWNER TO postgres;

--
-- Name: proxy_usage_stats_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: postgres
--

ALTER SEQUENCE public.proxy_usage_stats_id_seq OWNED BY public.proxy_usage_stats.id;


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
    binance_net_asset double precision DEFAULT 10000,
    bybit_mt5_net_asset double precision DEFAULT 10000,
    total_net_asset double precision DEFAULT 20000,
    binance_liquidation_price double precision DEFAULT 2000,
    bybit_mt5_liquidation_price double precision DEFAULT 2000,
    mt5_lag_count integer DEFAULT 5,
    reverse_open_price double precision DEFAULT 0.5,
    reverse_open_sync_count integer DEFAULT 3,
    reverse_close_price double precision DEFAULT 0.2,
    reverse_close_sync_count integer DEFAULT 3,
    forward_open_price double precision DEFAULT 0.5,
    forward_open_sync_count integer DEFAULT 3,
    forward_close_price double precision DEFAULT 0.2,
    forward_close_sync_count integer DEFAULT 3,
    create_time timestamp without time zone DEFAULT CURRENT_TIMESTAMP NOT NULL,
    update_time timestamp without time zone DEFAULT CURRENT_TIMESTAMP NOT NULL,
    spread_alert_sound character varying DEFAULT ''::character varying,
    net_asset_alert_sound character varying DEFAULT ''::character varying,
    mt5_alert_sound character varying DEFAULT ''::character varying,
    liquidation_alert_sound character varying DEFAULT ''::character varying,
    spread_alert_repeat_count integer DEFAULT 3,
    net_asset_alert_repeat_count integer DEFAULT 3,
    mt5_alert_repeat_count integer DEFAULT 3,
    liquidation_alert_repeat_count integer DEFAULT 3,
    single_leg_alert_sound character varying DEFAULT ''::character varying,
    single_leg_alert_repeat_count integer DEFAULT 3,
    pair_code character varying(30) DEFAULT 'XAU'::character varying NOT NULL,
    market_close_notify boolean DEFAULT false,
    funding_rate_threshold double precision,
    overnight_fee_threshold double precision,
    funding_rate_threshold_long double precision,
    overnight_fee_threshold_long double precision
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
-- Name: slippage_events; Type: TABLE; Schema: public; Owner: postgres
--

CREATE TABLE public.slippage_events (
    id bigint NOT NULL,
    user_id uuid NOT NULL,
    pair_code character varying(30) NOT NULL,
    strategy_type character varying(30) NOT NULL,
    spread_threshold double precision,
    actual_spread double precision,
    slippage double precision,
    level integer,
    binance_order_id character varying(50),
    binance_avg_price double precision,
    bybit_avg_price double precision,
    created_at timestamp without time zone DEFAULT now()
);


ALTER TABLE public.slippage_events OWNER TO postgres;

--
-- Name: slippage_events_id_seq; Type: SEQUENCE; Schema: public; Owner: postgres
--

CREATE SEQUENCE public.slippage_events_id_seq
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


ALTER SEQUENCE public.slippage_events_id_seq OWNER TO postgres;

--
-- Name: slippage_events_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: postgres
--

ALTER SEQUENCE public.slippage_events_id_seq OWNED BY public.slippage_events.id;


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
    "timestamp" timestamp without time zone NOT NULL,
    pair_code character varying(20)
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
    closing_trigger_check_interval double precision DEFAULT 0.5 NOT NULL,
    pair_code character varying(30) DEFAULT 'XAU'::character varying NOT NULL,
    hedge_multiplier double precision DEFAULT 1.0
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
    created_by uuid,
    spread_cancel_tolerance double precision DEFAULT 0.5
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
-- Name: sub_account_subscriptions; Type: TABLE; Schema: public; Owner: postgres
--

CREATE TABLE public.sub_account_subscriptions (
    id uuid DEFAULT gen_random_uuid() NOT NULL,
    sub_user_id uuid NOT NULL,
    parent_user_id uuid NOT NULL,
    invested_cny numeric(20,2) NOT NULL,
    fx_cny_to_usdt numeric(20,8) NOT NULL,
    invested_usdt numeric(20,8) NOT NULL,
    parent_total_assets_at_join numeric(20,8) NOT NULL,
    nav_per_share_at_join numeric(20,8) NOT NULL,
    shares numeric(20,8) NOT NULL,
    status character varying(20) DEFAULT 'active'::character varying NOT NULL,
    created_by uuid,
    created_at timestamp with time zone DEFAULT now() NOT NULL,
    updated_at timestamp with time zone DEFAULT now() NOT NULL,
    invested_at timestamp with time zone
);


ALTER TABLE public.sub_account_subscriptions OWNER TO postgres;

--
-- Name: subscription_daily_nav; Type: TABLE; Schema: public; Owner: postgres
--

CREATE TABLE public.subscription_daily_nav (
    id bigint NOT NULL,
    parent_user_id uuid NOT NULL,
    snapshot_date date NOT NULL,
    nav_per_share numeric(20,8) NOT NULL,
    total_assets_usdt numeric(20,8) NOT NULL,
    virtual_shares numeric(20,8) NOT NULL,
    active_sub_shares numeric(20,8) NOT NULL,
    source character varying(20) DEFAULT 'scheduled'::character varying,
    created_at timestamp with time zone DEFAULT now()
);


ALTER TABLE public.subscription_daily_nav OWNER TO postgres;

--
-- Name: subscription_daily_nav_id_seq; Type: SEQUENCE; Schema: public; Owner: postgres
--

CREATE SEQUENCE public.subscription_daily_nav_id_seq
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


ALTER SEQUENCE public.subscription_daily_nav_id_seq OWNER TO postgres;

--
-- Name: subscription_daily_nav_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: postgres
--

ALTER SEQUENCE public.subscription_daily_nav_id_seq OWNED BY public.subscription_daily_nav.id;


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
-- Name: system_announcements; Type: TABLE; Schema: public; Owner: postgres
--

CREATE TABLE public.system_announcements (
    id uuid DEFAULT gen_random_uuid() NOT NULL,
    title character varying(200) NOT NULL,
    content text NOT NULL,
    level character varying(20) DEFAULT 'info'::character varying NOT NULL,
    is_active boolean DEFAULT true NOT NULL,
    start_at timestamp with time zone,
    end_at timestamp with time zone,
    created_by uuid,
    created_at timestamp with time zone DEFAULT now() NOT NULL,
    updated_at timestamp with time zone DEFAULT now() NOT NULL,
    CONSTRAINT system_announcements_level_check CHECK (((level)::text = ANY ((ARRAY['info'::character varying, 'warning'::character varying, 'critical'::character varying])::text[])))
);


ALTER TABLE public.system_announcements OWNER TO postgres;

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
-- Name: system_maintenance_state; Type: TABLE; Schema: public; Owner: postgres
--

CREATE TABLE public.system_maintenance_state (
    id integer NOT NULL,
    is_active boolean DEFAULT false NOT NULL,
    reason text,
    started_at timestamp with time zone,
    scheduled_resume_at timestamp with time zone,
    activated_by uuid,
    updated_at timestamp with time zone DEFAULT now() NOT NULL,
    CONSTRAINT system_maintenance_state_id_check CHECK ((id = 1))
);


ALTER TABLE public.system_maintenance_state OWNER TO postgres;

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
-- Name: user_pair_accounts; Type: TABLE; Schema: public; Owner: postgres
--

CREATE TABLE public.user_pair_accounts (
    id integer NOT NULL,
    user_id uuid NOT NULL,
    pair_code character varying(20) NOT NULL,
    account_a_id uuid,
    account_b_id uuid,
    created_at timestamp without time zone DEFAULT now(),
    updated_at timestamp without time zone DEFAULT now()
);


ALTER TABLE public.user_pair_accounts OWNER TO postgres;

--
-- Name: user_pair_accounts_id_seq; Type: SEQUENCE; Schema: public; Owner: postgres
--

CREATE SEQUENCE public.user_pair_accounts_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


ALTER SEQUENCE public.user_pair_accounts_id_seq OWNER TO postgres;

--
-- Name: user_pair_accounts_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: postgres
--

ALTER SEQUENCE public.user_pair_accounts_id_seq OWNED BY public.user_pair_accounts.id;


--
-- Name: user_pnl_links; Type: TABLE; Schema: public; Owner: postgres
--

CREATE TABLE public.user_pnl_links (
    id integer NOT NULL,
    owner_user_id uuid NOT NULL,
    linked_user_id uuid NOT NULL,
    created_by uuid,
    created_at timestamp with time zone DEFAULT now()
);


ALTER TABLE public.user_pnl_links OWNER TO postgres;

--
-- Name: user_pnl_links_id_seq; Type: SEQUENCE; Schema: public; Owner: postgres
--

CREATE SEQUENCE public.user_pnl_links_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


ALTER SEQUENCE public.user_pnl_links_id_seq OWNER TO postgres;

--
-- Name: user_pnl_links_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: postgres
--

ALTER SEQUENCE public.user_pnl_links_id_seq OWNED BY public.user_pnl_links.id;


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
    user_id uuid DEFAULT gen_random_uuid() NOT NULL,
    username character varying(50) NOT NULL,
    password_hash character varying(256) NOT NULL,
    email character varying(100),
    create_time timestamp without time zone DEFAULT now() NOT NULL,
    update_time timestamp without time zone DEFAULT now() NOT NULL,
    is_active boolean DEFAULT true NOT NULL,
    role character varying(50) DEFAULT '交易员'::character varying NOT NULL,
    feishu_open_id character varying(100),
    feishu_mobile character varying(20),
    feishu_union_id character varying(100),
    hedge_ratio_enabled boolean DEFAULT false,
    openclaw_enabled boolean DEFAULT false NOT NULL,
    fund_view_enabled boolean DEFAULT false NOT NULL,
    parent_user_id uuid,
    is_subaccount boolean DEFAULT false NOT NULL,
    hedge_multiplier_options jsonb DEFAULT '[0.8, 0.9, 1.0, 1.1, 1.2, 1.3]'::jsonb
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
-- Name: agent_decisions_default; Type: TABLE ATTACH; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.agent_decisions ATTACH PARTITION public.agent_decisions_default DEFAULT;


--
-- Name: agent_decisions_y2026m04; Type: TABLE ATTACH; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.agent_decisions ATTACH PARTITION public.agent_decisions_y2026m04 FOR VALUES FROM ('2026-04-01 00:00:00+00') TO ('2026-05-01 00:00:00+00');


--
-- Name: agent_decisions_y2026m05; Type: TABLE ATTACH; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.agent_decisions ATTACH PARTITION public.agent_decisions_y2026m05 FOR VALUES FROM ('2026-05-01 00:00:00+00') TO ('2026-06-01 00:00:00+00');


--
-- Name: agent_decisions_y2026m06; Type: TABLE ATTACH; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.agent_decisions ATTACH PARTITION public.agent_decisions_y2026m06 FOR VALUES FROM ('2026-06-01 00:00:00+00') TO ('2026-07-01 00:00:00+00');


--
-- Name: agent_decisions_y2026m07; Type: TABLE ATTACH; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.agent_decisions ATTACH PARTITION public.agent_decisions_y2026m07 FOR VALUES FROM ('2026-07-01 00:00:00+00') TO ('2026-08-01 00:00:00+00');


--
-- Name: agent_decisions_y2026m08; Type: TABLE ATTACH; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.agent_decisions ATTACH PARTITION public.agent_decisions_y2026m08 FOR VALUES FROM ('2026-08-01 00:00:00+00') TO ('2026-09-01 00:00:00+00');


--
-- Name: agent_decisions_y2026m09; Type: TABLE ATTACH; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.agent_decisions ATTACH PARTITION public.agent_decisions_y2026m09 FOR VALUES FROM ('2026-09-01 00:00:00+00') TO ('2026-10-01 00:00:00+00');


--
-- Name: account_proxy_bindings id; Type: DEFAULT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.account_proxy_bindings ALTER COLUMN id SET DEFAULT nextval('public.account_proxy_bindings_id_seq'::regclass);


--
-- Name: agent_alerts id; Type: DEFAULT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.agent_alerts ALTER COLUMN id SET DEFAULT nextval('public.agent_alerts_id_seq'::regclass);


--
-- Name: agent_decisions_legacy id; Type: DEFAULT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.agent_decisions_legacy ALTER COLUMN id SET DEFAULT nextval('public.agent_decisions_legacy_id_seq'::regclass);


--
-- Name: agent_proposal_audit id; Type: DEFAULT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.agent_proposal_audit ALTER COLUMN id SET DEFAULT nextval('public.agent_proposal_audit_id_seq'::regclass);


--
-- Name: agent_proposals id; Type: DEFAULT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.agent_proposals ALTER COLUMN id SET DEFAULT nextval('public.agent_proposals_id_seq'::regclass);


--
-- Name: agent_scope_targets id; Type: DEFAULT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.agent_scope_targets ALTER COLUMN id SET DEFAULT nextval('public.agent_scope_targets_id_seq'::regclass);


--
-- Name: agent_strategy_proposals id; Type: DEFAULT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.agent_strategy_proposals ALTER COLUMN id SET DEFAULT nextval('public.agent_strategy_proposals_id_seq'::regclass);


--
-- Name: ai_arb_analysis id; Type: DEFAULT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.ai_arb_analysis ALTER COLUMN id SET DEFAULT nextval('public.ai_arb_analysis_id_seq'::regclass);


--
-- Name: aicoin_config id; Type: DEFAULT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.aicoin_config ALTER COLUMN id SET DEFAULT nextval('public.aicoin_config_id_seq'::regclass);


--
-- Name: binance_income id; Type: DEFAULT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.binance_income ALTER COLUMN id SET DEFAULT nextval('public.binance_income_id_seq'::regclass);


--
-- Name: equity_intervention_log id; Type: DEFAULT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.equity_intervention_log ALTER COLUMN id SET DEFAULT nextval('public.equity_intervention_log_id_seq'::regclass);


--
-- Name: hustle_chat_messages id; Type: DEFAULT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.hustle_chat_messages ALTER COLUMN id SET DEFAULT nextval('public.hustle_chat_messages_id_seq'::regclass);


--
-- Name: ladder_advisor_log id; Type: DEFAULT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.ladder_advisor_log ALTER COLUMN id SET DEFAULT nextval('public.ladder_advisor_log_id_seq'::regclass);


--
-- Name: leg_imbalance_log id; Type: DEFAULT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.leg_imbalance_log ALTER COLUMN id SET DEFAULT nextval('public.leg_imbalance_log_id_seq'::regclass);


--
-- Name: manual_ledger id; Type: DEFAULT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.manual_ledger ALTER COLUMN id SET DEFAULT nextval('public.manual_ledger_id_seq'::regclass);


--
-- Name: mt5_clients client_id; Type: DEFAULT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.mt5_clients ALTER COLUMN client_id SET DEFAULT nextval('public.mt5_clients_client_id_seq'::regclass);


--
-- Name: mt5_deals id; Type: DEFAULT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.mt5_deals ALTER COLUMN id SET DEFAULT nextval('public.mt5_deals_id_seq'::regclass);


--
-- Name: pair_rate_records id; Type: DEFAULT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.pair_rate_records ALTER COLUMN id SET DEFAULT nextval('public.pair_rate_records_id_seq'::regclass);


--
-- Name: pending_orders id; Type: DEFAULT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.pending_orders ALTER COLUMN id SET DEFAULT nextval('public.pending_orders_id_seq'::regclass);


--
-- Name: platforms platform_id; Type: DEFAULT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.platforms ALTER COLUMN platform_id SET DEFAULT nextval('public.platforms_platform_id_seq'::regclass);


--
-- Name: proxies proxy_id; Type: DEFAULT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.proxies ALTER COLUMN proxy_id SET DEFAULT nextval('public.proxies_proxy_id_seq'::regclass);


--
-- Name: proxy_health_logs id; Type: DEFAULT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.proxy_health_logs ALTER COLUMN id SET DEFAULT nextval('public.proxy_health_logs_id_seq'::regclass);


--
-- Name: proxy_pool id; Type: DEFAULT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.proxy_pool ALTER COLUMN id SET DEFAULT nextval('public.proxy_pool_id_seq'::regclass);


--
-- Name: proxy_usage_stats id; Type: DEFAULT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.proxy_usage_stats ALTER COLUMN id SET DEFAULT nextval('public.proxy_usage_stats_id_seq'::regclass);


--
-- Name: slippage_events id; Type: DEFAULT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.slippage_events ALTER COLUMN id SET DEFAULT nextval('public.slippage_events_id_seq'::regclass);


--
-- Name: strategies id; Type: DEFAULT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.strategies ALTER COLUMN id SET DEFAULT nextval('public.strategies_id_seq'::regclass);


--
-- Name: strategy_timing_configs id; Type: DEFAULT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.strategy_timing_configs ALTER COLUMN id SET DEFAULT nextval('public.strategy_timing_configs_id_seq'::regclass);


--
-- Name: subscription_daily_nav id; Type: DEFAULT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.subscription_daily_nav ALTER COLUMN id SET DEFAULT nextval('public.subscription_daily_nav_id_seq'::regclass);


--
-- Name: timing_config_history id; Type: DEFAULT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.timing_config_history ALTER COLUMN id SET DEFAULT nextval('public.timing_config_history_id_seq'::regclass);


--
-- Name: timing_config_templates id; Type: DEFAULT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.timing_config_templates ALTER COLUMN id SET DEFAULT nextval('public.timing_config_templates_id_seq'::regclass);


--
-- Name: user_pair_accounts id; Type: DEFAULT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.user_pair_accounts ALTER COLUMN id SET DEFAULT nextval('public.user_pair_accounts_id_seq'::regclass);


--
-- Name: user_pnl_links id; Type: DEFAULT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.user_pnl_links ALTER COLUMN id SET DEFAULT nextval('public.user_pnl_links_id_seq'::regclass);


--
-- Name: account_proxy_bindings account_proxy_bindings_pkey; Type: CONSTRAINT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.account_proxy_bindings
    ADD CONSTRAINT account_proxy_bindings_pkey PRIMARY KEY (id);


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
-- Name: agent_active_config agent_active_config_pkey; Type: CONSTRAINT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.agent_active_config
    ADD CONSTRAINT agent_active_config_pkey PRIMARY KEY (key);


--
-- Name: agent_alerts agent_alerts_pkey; Type: CONSTRAINT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.agent_alerts
    ADD CONSTRAINT agent_alerts_pkey PRIMARY KEY (id);


--
-- Name: agent_decisions agent_decisions_pkey; Type: CONSTRAINT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.agent_decisions
    ADD CONSTRAINT agent_decisions_pkey PRIMARY KEY (id, created_at);


--
-- Name: agent_decisions_default agent_decisions_default_pkey; Type: CONSTRAINT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.agent_decisions_default
    ADD CONSTRAINT agent_decisions_default_pkey PRIMARY KEY (id, created_at);


--
-- Name: agent_decisions_legacy agent_decisions_legacy_pkey; Type: CONSTRAINT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.agent_decisions_legacy
    ADD CONSTRAINT agent_decisions_legacy_pkey PRIMARY KEY (id);


--
-- Name: agent_decisions_y2026m04 agent_decisions_y2026m04_pkey; Type: CONSTRAINT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.agent_decisions_y2026m04
    ADD CONSTRAINT agent_decisions_y2026m04_pkey PRIMARY KEY (id, created_at);


--
-- Name: agent_decisions_y2026m05 agent_decisions_y2026m05_pkey; Type: CONSTRAINT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.agent_decisions_y2026m05
    ADD CONSTRAINT agent_decisions_y2026m05_pkey PRIMARY KEY (id, created_at);


--
-- Name: agent_decisions_y2026m06 agent_decisions_y2026m06_pkey; Type: CONSTRAINT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.agent_decisions_y2026m06
    ADD CONSTRAINT agent_decisions_y2026m06_pkey PRIMARY KEY (id, created_at);


--
-- Name: agent_decisions_y2026m07 agent_decisions_y2026m07_pkey; Type: CONSTRAINT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.agent_decisions_y2026m07
    ADD CONSTRAINT agent_decisions_y2026m07_pkey PRIMARY KEY (id, created_at);


--
-- Name: agent_decisions_y2026m08 agent_decisions_y2026m08_pkey; Type: CONSTRAINT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.agent_decisions_y2026m08
    ADD CONSTRAINT agent_decisions_y2026m08_pkey PRIMARY KEY (id, created_at);


--
-- Name: agent_decisions_y2026m09 agent_decisions_y2026m09_pkey; Type: CONSTRAINT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.agent_decisions_y2026m09
    ADD CONSTRAINT agent_decisions_y2026m09_pkey PRIMARY KEY (id, created_at);


--
-- Name: agent_proposal_audit agent_proposal_audit_pkey; Type: CONSTRAINT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.agent_proposal_audit
    ADD CONSTRAINT agent_proposal_audit_pkey PRIMARY KEY (id);


--
-- Name: agent_proposals agent_proposals_pkey; Type: CONSTRAINT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.agent_proposals
    ADD CONSTRAINT agent_proposals_pkey PRIMARY KEY (id);


--
-- Name: agent_scope_targets agent_scope_targets_pkey; Type: CONSTRAINT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.agent_scope_targets
    ADD CONSTRAINT agent_scope_targets_pkey PRIMARY KEY (id);


--
-- Name: agent_scope_targets agent_scope_targets_user_id_pair_code_key; Type: CONSTRAINT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.agent_scope_targets
    ADD CONSTRAINT agent_scope_targets_user_id_pair_code_key UNIQUE (user_id, pair_code);


--
-- Name: agent_state agent_state_pkey; Type: CONSTRAINT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.agent_state
    ADD CONSTRAINT agent_state_pkey PRIMARY KEY (id);


--
-- Name: agent_strategy_proposals agent_strategy_proposals_pkey; Type: CONSTRAINT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.agent_strategy_proposals
    ADD CONSTRAINT agent_strategy_proposals_pkey PRIMARY KEY (id);


--
-- Name: agent_target_config agent_target_config_pkey; Type: CONSTRAINT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.agent_target_config
    ADD CONSTRAINT agent_target_config_pkey PRIMARY KEY (target_id, key);


--
-- Name: ai_arb_analysis ai_arb_analysis_pkey; Type: CONSTRAINT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.ai_arb_analysis
    ADD CONSTRAINT ai_arb_analysis_pkey PRIMARY KEY (id);


--
-- Name: aicoin_config aicoin_config_pkey; Type: CONSTRAINT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.aicoin_config
    ADD CONSTRAINT aicoin_config_pkey PRIMARY KEY (id);


--
-- Name: alembic_version alembic_version_pkc; Type: CONSTRAINT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.alembic_version
    ADD CONSTRAINT alembic_version_pkc PRIMARY KEY (version_num);


--
-- Name: arbitrage_opportunities arbitrage_opportunities_pkey; Type: CONSTRAINT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.arbitrage_opportunities
    ADD CONSTRAINT arbitrage_opportunities_pkey PRIMARY KEY (id);


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
-- Name: binance_income binance_income_pkey; Type: CONSTRAINT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.binance_income
    ADD CONSTRAINT binance_income_pkey PRIMARY KEY (id);


--
-- Name: equity_intervention_log equity_intervention_log_pkey; Type: CONSTRAINT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.equity_intervention_log
    ADD CONSTRAINT equity_intervention_log_pkey PRIMARY KEY (id);


--
-- Name: hedge_batch_records hedge_batch_records_pkey; Type: CONSTRAINT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.hedge_batch_records
    ADD CONSTRAINT hedge_batch_records_pkey PRIMARY KEY (id);


--
-- Name: hedging_pairs hedging_pairs_pair_code_key; Type: CONSTRAINT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.hedging_pairs
    ADD CONSTRAINT hedging_pairs_pair_code_key UNIQUE (pair_code);


--
-- Name: hedging_pairs hedging_pairs_pkey; Type: CONSTRAINT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.hedging_pairs
    ADD CONSTRAINT hedging_pairs_pkey PRIMARY KEY (id);


--
-- Name: hustle_chat_messages hustle_chat_messages_pkey; Type: CONSTRAINT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.hustle_chat_messages
    ADD CONSTRAINT hustle_chat_messages_pkey PRIMARY KEY (id);


--
-- Name: ladder_advisor_config ladder_advisor_config_pkey; Type: CONSTRAINT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.ladder_advisor_config
    ADD CONSTRAINT ladder_advisor_config_pkey PRIMARY KEY (id);


--
-- Name: ladder_advisor_log ladder_advisor_log_pkey; Type: CONSTRAINT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.ladder_advisor_log
    ADD CONSTRAINT ladder_advisor_log_pkey PRIMARY KEY (id);


--
-- Name: leg_imbalance_log leg_imbalance_log_pkey; Type: CONSTRAINT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.leg_imbalance_log
    ADD CONSTRAINT leg_imbalance_log_pkey PRIMARY KEY (id);


--
-- Name: manual_ledger manual_ledger_pkey; Type: CONSTRAINT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.manual_ledger
    ADD CONSTRAINT manual_ledger_pkey PRIMARY KEY (id);


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
-- Name: mt5_config mt5_config_pkey; Type: CONSTRAINT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.mt5_config
    ADD CONSTRAINT mt5_config_pkey PRIMARY KEY (key);


--
-- Name: mt5_deals mt5_deals_pkey; Type: CONSTRAINT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.mt5_deals
    ADD CONSTRAINT mt5_deals_pkey PRIMARY KEY (id);


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
-- Name: notification_subscriptions notification_subscriptions_pkey; Type: CONSTRAINT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.notification_subscriptions
    ADD CONSTRAINT notification_subscriptions_pkey PRIMARY KEY (subscription_id);


--
-- Name: notification_subscriptions notification_subscriptions_subscriber_user_id_trader_user_i_key; Type: CONSTRAINT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.notification_subscriptions
    ADD CONSTRAINT notification_subscriptions_subscriber_user_id_trader_user_i_key UNIQUE (subscriber_user_id, trader_user_id, template_id);


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
-- Name: pair_rate_records pair_rate_records_pkey; Type: CONSTRAINT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.pair_rate_records
    ADD CONSTRAINT pair_rate_records_pkey PRIMARY KEY (id);


--
-- Name: parent_cashflow_events parent_cashflow_events_pkey; Type: CONSTRAINT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.parent_cashflow_events
    ADD CONSTRAINT parent_cashflow_events_pkey PRIMARY KEY (id);


--
-- Name: parent_share_state parent_share_state_pkey; Type: CONSTRAINT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.parent_share_state
    ADD CONSTRAINT parent_share_state_pkey PRIMARY KEY (parent_user_id);


--
-- Name: pending_orders pending_orders_pkey; Type: CONSTRAINT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.pending_orders
    ADD CONSTRAINT pending_orders_pkey PRIMARY KEY (id);


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
-- Name: platform_symbols platform_symbols_pkey; Type: CONSTRAINT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.platform_symbols
    ADD CONSTRAINT platform_symbols_pkey PRIMARY KEY (id);


--
-- Name: platform_symbols platform_symbols_platform_id_symbol_key; Type: CONSTRAINT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.platform_symbols
    ADD CONSTRAINT platform_symbols_platform_id_symbol_key UNIQUE (platform_id, symbol);


--
-- Name: platforms platforms_pkey; Type: CONSTRAINT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.platforms
    ADD CONSTRAINT platforms_pkey PRIMARY KEY (platform_id);


--
-- Name: pnl_sync_watermark pnl_sync_watermark_pkey; Type: CONSTRAINT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.pnl_sync_watermark
    ADD CONSTRAINT pnl_sync_watermark_pkey PRIMARY KEY (account_id, source);


--
-- Name: positions positions_pkey; Type: CONSTRAINT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.positions
    ADD CONSTRAINT positions_pkey PRIMARY KEY (position_id);


--
-- Name: proxies proxies_pkey; Type: CONSTRAINT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.proxies
    ADD CONSTRAINT proxies_pkey PRIMARY KEY (proxy_id);


--
-- Name: proxy_health_logs proxy_health_logs_pkey; Type: CONSTRAINT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.proxy_health_logs
    ADD CONSTRAINT proxy_health_logs_pkey PRIMARY KEY (id);


--
-- Name: proxy_pool proxy_pool_pkey; Type: CONSTRAINT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.proxy_pool
    ADD CONSTRAINT proxy_pool_pkey PRIMARY KEY (id);


--
-- Name: proxy_usage_stats proxy_usage_stats_pkey; Type: CONSTRAINT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.proxy_usage_stats
    ADD CONSTRAINT proxy_usage_stats_pkey PRIMARY KEY (id);


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
-- Name: risk_settings risk_settings_user_pair_key; Type: CONSTRAINT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.risk_settings
    ADD CONSTRAINT risk_settings_user_pair_key UNIQUE (user_id, pair_code);


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
-- Name: slippage_events slippage_events_pkey; Type: CONSTRAINT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.slippage_events
    ADD CONSTRAINT slippage_events_pkey PRIMARY KEY (id);


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
-- Name: strategy_configs strategy_configs_user_pair_type_key; Type: CONSTRAINT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.strategy_configs
    ADD CONSTRAINT strategy_configs_user_pair_type_key UNIQUE (user_id, strategy_type, pair_code);


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
-- Name: sub_account_subscriptions sub_account_subscriptions_pkey; Type: CONSTRAINT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.sub_account_subscriptions
    ADD CONSTRAINT sub_account_subscriptions_pkey PRIMARY KEY (id);


--
-- Name: subscription_daily_nav subscription_daily_nav_pkey; Type: CONSTRAINT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.subscription_daily_nav
    ADD CONSTRAINT subscription_daily_nav_pkey PRIMARY KEY (id);


--
-- Name: system_alerts system_alerts_pkey; Type: CONSTRAINT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.system_alerts
    ADD CONSTRAINT system_alerts_pkey PRIMARY KEY (alert_id);


--
-- Name: system_announcements system_announcements_pkey; Type: CONSTRAINT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.system_announcements
    ADD CONSTRAINT system_announcements_pkey PRIMARY KEY (id);


--
-- Name: system_logs system_logs_pkey; Type: CONSTRAINT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.system_logs
    ADD CONSTRAINT system_logs_pkey PRIMARY KEY (log_id);


--
-- Name: system_maintenance_state system_maintenance_state_pkey; Type: CONSTRAINT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.system_maintenance_state
    ADD CONSTRAINT system_maintenance_state_pkey PRIMARY KEY (id);


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
-- Name: manual_ledger uix_mledger_user_date; Type: CONSTRAINT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.manual_ledger
    ADD CONSTRAINT uix_mledger_user_date UNIQUE (user_id, entry_date);


--
-- Name: mt5_deals uix_mt5_deals_acct_ticket; Type: CONSTRAINT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.mt5_deals
    ADD CONSTRAINT uix_mt5_deals_acct_ticket UNIQUE (account_id, ticket);


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
-- Name: user_pair_accounts user_pair_accounts_pkey; Type: CONSTRAINT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.user_pair_accounts
    ADD CONSTRAINT user_pair_accounts_pkey PRIMARY KEY (id);


--
-- Name: user_pair_accounts user_pair_accounts_user_id_pair_code_key; Type: CONSTRAINT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.user_pair_accounts
    ADD CONSTRAINT user_pair_accounts_user_id_pair_code_key UNIQUE (user_id, pair_code);


--
-- Name: user_pnl_links user_pnl_links_owner_user_id_linked_user_id_key; Type: CONSTRAINT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.user_pnl_links
    ADD CONSTRAINT user_pnl_links_owner_user_id_linked_user_id_key UNIQUE (owner_user_id, linked_user_id);


--
-- Name: user_pnl_links user_pnl_links_pkey; Type: CONSTRAINT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.user_pnl_links
    ADD CONSTRAINT user_pnl_links_pkey PRIMARY KEY (id);


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
-- Name: idx_agent_alerts_created; Type: INDEX; Schema: public; Owner: postgres
--

CREATE INDEX idx_agent_alerts_created ON public.agent_alerts USING btree (created_at DESC);


--
-- Name: idx_agent_decisions_default_created; Type: INDEX; Schema: public; Owner: postgres
--

CREATE INDEX idx_agent_decisions_default_created ON public.agent_decisions_default USING btree (created_at DESC);


--
-- Name: idx_agent_decisions_default_scope; Type: INDEX; Schema: public; Owner: postgres
--

CREATE INDEX idx_agent_decisions_default_scope ON public.agent_decisions_default USING btree (scope_target_id, created_at DESC);


--
-- Name: idx_agent_decisions_default_verdict; Type: INDEX; Schema: public; Owner: postgres
--

CREATE INDEX idx_agent_decisions_default_verdict ON public.agent_decisions_default USING btree (verdict, created_at DESC);


--
-- Name: idx_agent_decisions_legacy_created; Type: INDEX; Schema: public; Owner: postgres
--

CREATE INDEX idx_agent_decisions_legacy_created ON public.agent_decisions_legacy USING btree (created_at DESC);


--
-- Name: idx_agent_decisions_legacy_scope; Type: INDEX; Schema: public; Owner: postgres
--

CREATE INDEX idx_agent_decisions_legacy_scope ON public.agent_decisions_legacy USING btree (scope_target_id, created_at DESC);


--
-- Name: idx_agent_decisions_legacy_verdict; Type: INDEX; Schema: public; Owner: postgres
--

CREATE INDEX idx_agent_decisions_legacy_verdict ON public.agent_decisions_legacy USING btree (verdict, created_at DESC);


--
-- Name: idx_agent_decisions_y2026m04_created; Type: INDEX; Schema: public; Owner: postgres
--

CREATE INDEX idx_agent_decisions_y2026m04_created ON public.agent_decisions_y2026m04 USING btree (created_at DESC);


--
-- Name: idx_agent_decisions_y2026m04_scope; Type: INDEX; Schema: public; Owner: postgres
--

CREATE INDEX idx_agent_decisions_y2026m04_scope ON public.agent_decisions_y2026m04 USING btree (scope_target_id, created_at DESC);


--
-- Name: idx_agent_decisions_y2026m04_verdict; Type: INDEX; Schema: public; Owner: postgres
--

CREATE INDEX idx_agent_decisions_y2026m04_verdict ON public.agent_decisions_y2026m04 USING btree (verdict, created_at DESC);


--
-- Name: idx_agent_decisions_y2026m05_created; Type: INDEX; Schema: public; Owner: postgres
--

CREATE INDEX idx_agent_decisions_y2026m05_created ON public.agent_decisions_y2026m05 USING btree (created_at DESC);


--
-- Name: idx_agent_decisions_y2026m05_scope; Type: INDEX; Schema: public; Owner: postgres
--

CREATE INDEX idx_agent_decisions_y2026m05_scope ON public.agent_decisions_y2026m05 USING btree (scope_target_id, created_at DESC);


--
-- Name: idx_agent_decisions_y2026m05_verdict; Type: INDEX; Schema: public; Owner: postgres
--

CREATE INDEX idx_agent_decisions_y2026m05_verdict ON public.agent_decisions_y2026m05 USING btree (verdict, created_at DESC);


--
-- Name: idx_agent_decisions_y2026m06_created; Type: INDEX; Schema: public; Owner: postgres
--

CREATE INDEX idx_agent_decisions_y2026m06_created ON public.agent_decisions_y2026m06 USING btree (created_at DESC);


--
-- Name: idx_agent_decisions_y2026m06_scope; Type: INDEX; Schema: public; Owner: postgres
--

CREATE INDEX idx_agent_decisions_y2026m06_scope ON public.agent_decisions_y2026m06 USING btree (scope_target_id, created_at DESC);


--
-- Name: idx_agent_decisions_y2026m06_verdict; Type: INDEX; Schema: public; Owner: postgres
--

CREATE INDEX idx_agent_decisions_y2026m06_verdict ON public.agent_decisions_y2026m06 USING btree (verdict, created_at DESC);


--
-- Name: idx_agent_decisions_y2026m07_created; Type: INDEX; Schema: public; Owner: postgres
--

CREATE INDEX idx_agent_decisions_y2026m07_created ON public.agent_decisions_y2026m07 USING btree (created_at DESC);


--
-- Name: idx_agent_decisions_y2026m07_scope; Type: INDEX; Schema: public; Owner: postgres
--

CREATE INDEX idx_agent_decisions_y2026m07_scope ON public.agent_decisions_y2026m07 USING btree (scope_target_id, created_at DESC);


--
-- Name: idx_agent_decisions_y2026m07_verdict; Type: INDEX; Schema: public; Owner: postgres
--

CREATE INDEX idx_agent_decisions_y2026m07_verdict ON public.agent_decisions_y2026m07 USING btree (verdict, created_at DESC);


--
-- Name: idx_agent_decisions_y2026m08_created; Type: INDEX; Schema: public; Owner: postgres
--

CREATE INDEX idx_agent_decisions_y2026m08_created ON public.agent_decisions_y2026m08 USING btree (created_at DESC);


--
-- Name: idx_agent_decisions_y2026m08_scope; Type: INDEX; Schema: public; Owner: postgres
--

CREATE INDEX idx_agent_decisions_y2026m08_scope ON public.agent_decisions_y2026m08 USING btree (scope_target_id, created_at DESC);


--
-- Name: idx_agent_decisions_y2026m08_verdict; Type: INDEX; Schema: public; Owner: postgres
--

CREATE INDEX idx_agent_decisions_y2026m08_verdict ON public.agent_decisions_y2026m08 USING btree (verdict, created_at DESC);


--
-- Name: idx_agent_decisions_y2026m09_created; Type: INDEX; Schema: public; Owner: postgres
--

CREATE INDEX idx_agent_decisions_y2026m09_created ON public.agent_decisions_y2026m09 USING btree (created_at DESC);


--
-- Name: idx_agent_decisions_y2026m09_scope; Type: INDEX; Schema: public; Owner: postgres
--

CREATE INDEX idx_agent_decisions_y2026m09_scope ON public.agent_decisions_y2026m09 USING btree (scope_target_id, created_at DESC);


--
-- Name: idx_agent_decisions_y2026m09_verdict; Type: INDEX; Schema: public; Owner: postgres
--

CREATE INDEX idx_agent_decisions_y2026m09_verdict ON public.agent_decisions_y2026m09 USING btree (verdict, created_at DESC);


--
-- Name: idx_agent_proposal_audit_pid; Type: INDEX; Schema: public; Owner: postgres
--

CREATE INDEX idx_agent_proposal_audit_pid ON public.agent_proposal_audit USING btree (proposal_id);


--
-- Name: idx_agent_proposals_status; Type: INDEX; Schema: public; Owner: postgres
--

CREATE INDEX idx_agent_proposals_status ON public.agent_proposals USING btree (status);


--
-- Name: idx_agent_proposals_target; Type: INDEX; Schema: public; Owner: postgres
--

CREATE INDEX idx_agent_proposals_target ON public.agent_proposals USING btree (target_id);


--
-- Name: idx_announce_active; Type: INDEX; Schema: public; Owner: postgres
--

CREATE INDEX idx_announce_active ON public.system_announcements USING btree (is_active, start_at, end_at);


--
-- Name: idx_arb_opp_symbol; Type: INDEX; Schema: public; Owner: postgres
--

CREATE INDEX idx_arb_opp_symbol ON public.arbitrage_opportunities USING btree (symbol);


--
-- Name: idx_arb_opp_symbol_time; Type: INDEX; Schema: public; Owner: postgres
--

CREATE INDEX idx_arb_opp_symbol_time ON public.arbitrage_opportunities USING btree (symbol, "timestamp");


--
-- Name: idx_arb_opp_timestamp; Type: INDEX; Schema: public; Owner: postgres
--

CREATE INDEX idx_arb_opp_timestamp ON public.arbitrage_opportunities USING btree ("timestamp");


--
-- Name: idx_arb_opp_type; Type: INDEX; Schema: public; Owner: postgres
--

CREATE INDEX idx_arb_opp_type ON public.arbitrage_opportunities USING btree (opportunity_type);


--
-- Name: idx_arb_opp_type_time; Type: INDEX; Schema: public; Owner: postgres
--

CREATE INDEX idx_arb_opp_type_time ON public.arbitrage_opportunities USING btree (opportunity_type, "timestamp");


--
-- Name: idx_binance_income_acct_time; Type: INDEX; Schema: public; Owner: postgres
--

CREATE INDEX idx_binance_income_acct_time ON public.binance_income USING btree (account_id, income_time_ms);


--
-- Name: idx_binance_income_type_time; Type: INDEX; Schema: public; Owner: postgres
--

CREATE INDEX idx_binance_income_type_time ON public.binance_income USING btree (account_id, income_type, income_time_ms);


--
-- Name: idx_chat_user_site; Type: INDEX; Schema: public; Owner: postgres
--

CREATE INDEX idx_chat_user_site ON public.hustle_chat_messages USING btree (user_id, site, created_at DESC);


--
-- Name: idx_equity_intervention_account; Type: INDEX; Schema: public; Owner: postgres
--

CREATE INDEX idx_equity_intervention_account ON public.equity_intervention_log USING btree (account_id, triggered_at DESC);


--
-- Name: idx_hedging_pairs_active; Type: INDEX; Schema: public; Owner: postgres
--

CREATE INDEX idx_hedging_pairs_active ON public.hedging_pairs USING btree (is_active, sort_order);


--
-- Name: idx_ladvlog_target_time; Type: INDEX; Schema: public; Owner: postgres
--

CREATE INDEX idx_ladvlog_target_time ON public.ladder_advisor_log USING btree (user_id, strategy_type, pair_code, created_at);


--
-- Name: idx_market_data_symbol_platform_time; Type: INDEX; Schema: public; Owner: postgres
--

CREATE INDEX idx_market_data_symbol_platform_time ON public.market_data USING btree (symbol, platform, "timestamp");


--
-- Name: idx_mledger_user_date; Type: INDEX; Schema: public; Owner: postgres
--

CREATE INDEX idx_mledger_user_date ON public.manual_ledger USING btree (user_id, entry_date DESC);


--
-- Name: idx_mt5_clients_system_service; Type: INDEX; Schema: public; Owner: postgres
--

CREATE INDEX idx_mt5_clients_system_service ON public.mt5_clients USING btree (is_system_service);


--
-- Name: idx_mt5_deals_acct_entry_time; Type: INDEX; Schema: public; Owner: postgres
--

CREATE INDEX idx_mt5_deals_acct_entry_time ON public.mt5_deals USING btree (account_id, entry, deal_time_utc);


--
-- Name: idx_mt5_deals_acct_time; Type: INDEX; Schema: public; Owner: postgres
--

CREATE INDEX idx_mt5_deals_acct_time ON public.mt5_deals USING btree (account_id, deal_time_utc);


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
-- Name: idx_notif_sub_subscriber; Type: INDEX; Schema: public; Owner: postgres
--

CREATE INDEX idx_notif_sub_subscriber ON public.notification_subscriptions USING btree (subscriber_user_id);


--
-- Name: idx_notif_sub_trader; Type: INDEX; Schema: public; Owner: postgres
--

CREATE INDEX idx_notif_sub_trader ON public.notification_subscriptions USING btree (trader_user_id);


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
-- Name: idx_pair_rate_records_pc_ts; Type: INDEX; Schema: public; Owner: postgres
--

CREATE INDEX idx_pair_rate_records_pc_ts ON public.pair_rate_records USING btree (pair_code, "timestamp");


--
-- Name: idx_pce_parent_time; Type: INDEX; Schema: public; Owner: postgres
--

CREATE INDEX idx_pce_parent_time ON public.parent_cashflow_events USING btree (parent_user_id, created_at DESC);


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
-- Name: idx_platform_symbols_platform; Type: INDEX; Schema: public; Owner: postgres
--

CREATE INDEX idx_platform_symbols_platform ON public.platform_symbols USING btree (platform_id);


--
-- Name: idx_positions_user_open; Type: INDEX; Schema: public; Owner: postgres
--

CREATE INDEX idx_positions_user_open ON public.positions USING btree (user_id, is_open);


--
-- Name: idx_proposal_audit_actor; Type: INDEX; Schema: public; Owner: postgres
--

CREATE INDEX idx_proposal_audit_actor ON public.agent_proposal_audit USING btree (actor_user_id, created_at DESC);


--
-- Name: idx_proposal_audit_pid; Type: INDEX; Schema: public; Owner: postgres
--

CREATE INDEX idx_proposal_audit_pid ON public.agent_proposal_audit USING btree (proposal_id, created_at);


--
-- Name: idx_proposals_target; Type: INDEX; Schema: public; Owner: postgres
--

CREATE INDEX idx_proposals_target ON public.agent_strategy_proposals USING btree (target_id);


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
-- Name: idx_sas_parent; Type: INDEX; Schema: public; Owner: postgres
--

CREATE INDEX idx_sas_parent ON public.sub_account_subscriptions USING btree (parent_user_id);


--
-- Name: idx_sas_status; Type: INDEX; Schema: public; Owner: postgres
--

CREATE INDEX idx_sas_status ON public.sub_account_subscriptions USING btree (status);


--
-- Name: idx_sas_sub; Type: INDEX; Schema: public; Owner: postgres
--

CREATE INDEX idx_sas_sub ON public.sub_account_subscriptions USING btree (sub_user_id);


--
-- Name: idx_scope_targets_enabled; Type: INDEX; Schema: public; Owner: postgres
--

CREATE INDEX idx_scope_targets_enabled ON public.agent_scope_targets USING btree (enabled, priority);


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
-- Name: idx_slippage_events_user_pair; Type: INDEX; Schema: public; Owner: postgres
--

CREATE INDEX idx_slippage_events_user_pair ON public.slippage_events USING btree (user_id, pair_code, created_at DESC);


--
-- Name: idx_spread_records_pc_ts; Type: INDEX; Schema: public; Owner: postgres
--

CREATE INDEX idx_spread_records_pc_ts ON public.spread_records USING btree (pair_code, "timestamp");


--
-- Name: idx_spread_records_symbol_ts; Type: INDEX; Schema: public; Owner: postgres
--

CREATE INDEX idx_spread_records_symbol_ts ON public.spread_records USING btree (symbol, "timestamp" DESC);


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
-- Name: idx_sub_daily_nav_date; Type: INDEX; Schema: public; Owner: postgres
--

CREATE INDEX idx_sub_daily_nav_date ON public.subscription_daily_nav USING btree (snapshot_date);


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
-- Name: idx_upa_user_pair; Type: INDEX; Schema: public; Owner: postgres
--

CREATE INDEX idx_upa_user_pair ON public.user_pair_accounts USING btree (user_id, pair_code);


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
-- Name: idx_users_parent_user_id; Type: INDEX; Schema: public; Owner: postgres
--

CREATE INDEX idx_users_parent_user_id ON public.users USING btree (parent_user_id);


--
-- Name: ix_accounts_user_id; Type: INDEX; Schema: public; Owner: postgres
--

CREATE INDEX ix_accounts_user_id ON public.accounts USING btree (user_id);


--
-- Name: ix_arbitrage_tasks_user_id; Type: INDEX; Schema: public; Owner: postgres
--

CREATE INDEX ix_arbitrage_tasks_user_id ON public.arbitrage_tasks USING btree (user_id);


--
-- Name: ix_hedge_batch_records_pair_code; Type: INDEX; Schema: public; Owner: postgres
--

CREATE INDEX ix_hedge_batch_records_pair_code ON public.hedge_batch_records USING btree (pair_code);


--
-- Name: ix_hedge_batch_records_user_id; Type: INDEX; Schema: public; Owner: postgres
--

CREATE INDEX ix_hedge_batch_records_user_id ON public.hedge_batch_records USING btree (user_id);


--
-- Name: ix_market_data_timestamp; Type: INDEX; Schema: public; Owner: postgres
--

CREATE INDEX ix_market_data_timestamp ON public.market_data USING btree ("timestamp");


--
-- Name: ix_order_records_account_id; Type: INDEX; Schema: public; Owner: postgres
--

CREATE INDEX ix_order_records_account_id ON public.order_records USING btree (account_id);


--
-- Name: ix_pending_orders_created_at; Type: INDEX; Schema: public; Owner: postgres
--

CREATE INDEX ix_pending_orders_created_at ON public.pending_orders USING btree (created_at);


--
-- Name: ix_pending_orders_status; Type: INDEX; Schema: public; Owner: postgres
--

CREATE INDEX ix_pending_orders_status ON public.pending_orders USING btree (status);


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
-- Name: ix_upl_owner; Type: INDEX; Schema: public; Owner: postgres
--

CREATE INDEX ix_upl_owner ON public.user_pnl_links USING btree (owner_user_id);


--
-- Name: ix_users_email; Type: INDEX; Schema: public; Owner: postgres
--

CREATE UNIQUE INDEX ix_users_email ON public.users USING btree (email);


--
-- Name: ix_users_username; Type: INDEX; Schema: public; Owner: postgres
--

CREATE UNIQUE INDEX ix_users_username ON public.users USING btree (username);


--
-- Name: uix_binance_income_dedup; Type: INDEX; Schema: public; Owner: postgres
--

CREATE UNIQUE INDEX uix_binance_income_dedup ON public.binance_income USING btree (account_id, dedup_key);


--
-- Name: uix_sub_daily_nav_parent_date; Type: INDEX; Schema: public; Owner: postgres
--

CREATE UNIQUE INDEX uix_sub_daily_nav_parent_date ON public.subscription_daily_nav USING btree (parent_user_id, snapshot_date);


--
-- Name: uq_user_platform_hedge; Type: INDEX; Schema: public; Owner: postgres
--

CREATE UNIQUE INDEX uq_user_platform_hedge ON public.accounts USING btree (user_id, platform_id) WHERE ((account_role)::text = 'hedge'::text);


--
-- Name: uq_user_primary; Type: INDEX; Schema: public; Owner: postgres
--

CREATE UNIQUE INDEX uq_user_primary ON public.accounts USING btree (user_id) WHERE ((account_role)::text = 'primary'::text);


--
-- Name: agent_decisions_default_pkey; Type: INDEX ATTACH; Schema: public; Owner: postgres
--

ALTER INDEX public.agent_decisions_pkey ATTACH PARTITION public.agent_decisions_default_pkey;


--
-- Name: agent_decisions_y2026m04_pkey; Type: INDEX ATTACH; Schema: public; Owner: postgres
--

ALTER INDEX public.agent_decisions_pkey ATTACH PARTITION public.agent_decisions_y2026m04_pkey;


--
-- Name: agent_decisions_y2026m05_pkey; Type: INDEX ATTACH; Schema: public; Owner: postgres
--

ALTER INDEX public.agent_decisions_pkey ATTACH PARTITION public.agent_decisions_y2026m05_pkey;


--
-- Name: agent_decisions_y2026m06_pkey; Type: INDEX ATTACH; Schema: public; Owner: postgres
--

ALTER INDEX public.agent_decisions_pkey ATTACH PARTITION public.agent_decisions_y2026m06_pkey;


--
-- Name: agent_decisions_y2026m07_pkey; Type: INDEX ATTACH; Schema: public; Owner: postgres
--

ALTER INDEX public.agent_decisions_pkey ATTACH PARTITION public.agent_decisions_y2026m07_pkey;


--
-- Name: agent_decisions_y2026m08_pkey; Type: INDEX ATTACH; Schema: public; Owner: postgres
--

ALTER INDEX public.agent_decisions_pkey ATTACH PARTITION public.agent_decisions_y2026m08_pkey;


--
-- Name: agent_decisions_y2026m09_pkey; Type: INDEX ATTACH; Schema: public; Owner: postgres
--

ALTER INDEX public.agent_decisions_pkey ATTACH PARTITION public.agent_decisions_y2026m09_pkey;


--
-- Name: accounts accounts_is_active_sync; Type: TRIGGER; Schema: public; Owner: postgres
--

CREATE TRIGGER accounts_is_active_sync BEFORE UPDATE ON public.accounts FOR EACH ROW EXECUTE FUNCTION public.trg_accounts_is_active_to_status();


--
-- Name: accounts accounts_status_sync; Type: TRIGGER; Schema: public; Owner: postgres
--

CREATE TRIGGER accounts_status_sync BEFORE UPDATE ON public.accounts FOR EACH ROW EXECUTE FUNCTION public.trg_accounts_status_to_is_active();


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
-- Name: account_proxy_bindings account_proxy_bindings_account_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.account_proxy_bindings
    ADD CONSTRAINT account_proxy_bindings_account_id_fkey FOREIGN KEY (account_id) REFERENCES public.accounts(account_id) ON DELETE CASCADE;


--
-- Name: account_proxy_bindings account_proxy_bindings_proxy_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.account_proxy_bindings
    ADD CONSTRAINT account_proxy_bindings_proxy_id_fkey FOREIGN KEY (proxy_id) REFERENCES public.proxy_pool(id) ON DELETE CASCADE;


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
-- Name: agent_active_config agent_active_config_source_proposal_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.agent_active_config
    ADD CONSTRAINT agent_active_config_source_proposal_id_fkey FOREIGN KEY (source_proposal_id) REFERENCES public.agent_strategy_proposals(id);


--
-- Name: agent_proposal_audit agent_proposal_audit_proposal_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.agent_proposal_audit
    ADD CONSTRAINT agent_proposal_audit_proposal_id_fkey FOREIGN KEY (proposal_id) REFERENCES public.agent_strategy_proposals(id) ON DELETE CASCADE;


--
-- Name: agent_proposals agent_proposals_target_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.agent_proposals
    ADD CONSTRAINT agent_proposals_target_id_fkey FOREIGN KEY (target_id) REFERENCES public.agent_scope_targets(id) ON DELETE SET NULL;


--
-- Name: agent_scope_targets agent_scope_targets_user_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.agent_scope_targets
    ADD CONSTRAINT agent_scope_targets_user_id_fkey FOREIGN KEY (user_id) REFERENCES public.users(user_id) ON DELETE CASCADE;


--
-- Name: agent_strategy_proposals agent_strategy_proposals_target_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.agent_strategy_proposals
    ADD CONSTRAINT agent_strategy_proposals_target_id_fkey FOREIGN KEY (target_id) REFERENCES public.agent_scope_targets(id) ON DELETE SET NULL;


--
-- Name: agent_target_config agent_target_config_source_proposal_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.agent_target_config
    ADD CONSTRAINT agent_target_config_source_proposal_id_fkey FOREIGN KEY (source_proposal_id) REFERENCES public.agent_strategy_proposals(id);


--
-- Name: agent_target_config agent_target_config_target_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.agent_target_config
    ADD CONSTRAINT agent_target_config_target_id_fkey FOREIGN KEY (target_id) REFERENCES public.agent_scope_targets(id) ON DELETE CASCADE;


--
-- Name: arbitrage_tasks arbitrage_tasks_user_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.arbitrage_tasks
    ADD CONSTRAINT arbitrage_tasks_user_id_fkey FOREIGN KEY (user_id) REFERENCES public.users(user_id);


--
-- Name: binance_income binance_income_account_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.binance_income
    ADD CONSTRAINT binance_income_account_id_fkey FOREIGN KEY (account_id) REFERENCES public.accounts(account_id) ON DELETE CASCADE;


--
-- Name: strategy_timing_configs fk_timing_configs_created_by; Type: FK CONSTRAINT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.strategy_timing_configs
    ADD CONSTRAINT fk_timing_configs_created_by FOREIGN KEY (created_by) REFERENCES public.users(user_id) ON DELETE SET NULL;


--
-- Name: hedge_batch_records hedge_batch_records_user_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.hedge_batch_records
    ADD CONSTRAINT hedge_batch_records_user_id_fkey FOREIGN KEY (user_id) REFERENCES public.users(user_id);


--
-- Name: hedging_pairs hedging_pairs_account_a_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.hedging_pairs
    ADD CONSTRAINT hedging_pairs_account_a_id_fkey FOREIGN KEY (account_a_id) REFERENCES public.accounts(account_id);


--
-- Name: hedging_pairs hedging_pairs_account_b_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.hedging_pairs
    ADD CONSTRAINT hedging_pairs_account_b_id_fkey FOREIGN KEY (account_b_id) REFERENCES public.accounts(account_id);


--
-- Name: hedging_pairs hedging_pairs_symbol_a_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.hedging_pairs
    ADD CONSTRAINT hedging_pairs_symbol_a_id_fkey FOREIGN KEY (symbol_a_id) REFERENCES public.platform_symbols(id);


--
-- Name: hedging_pairs hedging_pairs_symbol_b_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.hedging_pairs
    ADD CONSTRAINT hedging_pairs_symbol_b_id_fkey FOREIGN KEY (symbol_b_id) REFERENCES public.platform_symbols(id);


--
-- Name: manual_ledger manual_ledger_user_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.manual_ledger
    ADD CONSTRAINT manual_ledger_user_id_fkey FOREIGN KEY (user_id) REFERENCES public.users(user_id) ON DELETE CASCADE;


--
-- Name: mt5_clients mt5_clients_account_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.mt5_clients
    ADD CONSTRAINT mt5_clients_account_id_fkey FOREIGN KEY (account_id) REFERENCES public.accounts(account_id) ON DELETE CASCADE;


--
-- Name: mt5_deals mt5_deals_account_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.mt5_deals
    ADD CONSTRAINT mt5_deals_account_id_fkey FOREIGN KEY (account_id) REFERENCES public.accounts(account_id) ON DELETE CASCADE;


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
-- Name: notification_subscriptions notification_subscriptions_subscriber_user_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.notification_subscriptions
    ADD CONSTRAINT notification_subscriptions_subscriber_user_id_fkey FOREIGN KEY (subscriber_user_id) REFERENCES public.users(user_id) ON DELETE CASCADE;


--
-- Name: notification_subscriptions notification_subscriptions_template_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.notification_subscriptions
    ADD CONSTRAINT notification_subscriptions_template_id_fkey FOREIGN KEY (template_id) REFERENCES public.notification_templates(template_id) ON DELETE CASCADE;


--
-- Name: notification_subscriptions notification_subscriptions_trader_user_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.notification_subscriptions
    ADD CONSTRAINT notification_subscriptions_trader_user_id_fkey FOREIGN KEY (trader_user_id) REFERENCES public.users(user_id) ON DELETE CASCADE;


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
-- Name: parent_cashflow_events parent_cashflow_events_created_by_fkey; Type: FK CONSTRAINT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.parent_cashflow_events
    ADD CONSTRAINT parent_cashflow_events_created_by_fkey FOREIGN KEY (created_by) REFERENCES public.users(user_id);


--
-- Name: parent_cashflow_events parent_cashflow_events_parent_user_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.parent_cashflow_events
    ADD CONSTRAINT parent_cashflow_events_parent_user_id_fkey FOREIGN KEY (parent_user_id) REFERENCES public.users(user_id) ON DELETE CASCADE;


--
-- Name: parent_share_state parent_share_state_parent_user_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.parent_share_state
    ADD CONSTRAINT parent_share_state_parent_user_id_fkey FOREIGN KEY (parent_user_id) REFERENCES public.users(user_id) ON DELETE CASCADE;


--
-- Name: pending_orders pending_orders_user_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.pending_orders
    ADD CONSTRAINT pending_orders_user_id_fkey FOREIGN KEY (user_id) REFERENCES public.users(user_id);


--
-- Name: permissions permissions_parent_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.permissions
    ADD CONSTRAINT permissions_parent_id_fkey FOREIGN KEY (parent_id) REFERENCES public.permissions(permission_id);


--
-- Name: platform_symbols platform_symbols_platform_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.platform_symbols
    ADD CONSTRAINT platform_symbols_platform_id_fkey FOREIGN KEY (platform_id) REFERENCES public.platforms(platform_id);


--
-- Name: pnl_sync_watermark pnl_sync_watermark_account_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.pnl_sync_watermark
    ADD CONSTRAINT pnl_sync_watermark_account_id_fkey FOREIGN KEY (account_id) REFERENCES public.accounts(account_id) ON DELETE CASCADE;


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
-- Name: proxies proxies_user_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.proxies
    ADD CONSTRAINT proxies_user_id_fkey FOREIGN KEY (user_id) REFERENCES public.users(user_id);


--
-- Name: proxy_health_logs proxy_health_logs_proxy_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.proxy_health_logs
    ADD CONSTRAINT proxy_health_logs_proxy_id_fkey FOREIGN KEY (proxy_id) REFERENCES public.proxy_pool(id) ON DELETE CASCADE;


--
-- Name: proxy_usage_stats proxy_usage_stats_account_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.proxy_usage_stats
    ADD CONSTRAINT proxy_usage_stats_account_id_fkey FOREIGN KEY (account_id) REFERENCES public.accounts(account_id) ON DELETE CASCADE;


--
-- Name: proxy_usage_stats proxy_usage_stats_proxy_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.proxy_usage_stats
    ADD CONSTRAINT proxy_usage_stats_proxy_id_fkey FOREIGN KEY (proxy_id) REFERENCES public.proxy_pool(id) ON DELETE CASCADE;


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
-- Name: sub_account_subscriptions sub_account_subscriptions_created_by_fkey; Type: FK CONSTRAINT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.sub_account_subscriptions
    ADD CONSTRAINT sub_account_subscriptions_created_by_fkey FOREIGN KEY (created_by) REFERENCES public.users(user_id);


--
-- Name: sub_account_subscriptions sub_account_subscriptions_parent_user_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.sub_account_subscriptions
    ADD CONSTRAINT sub_account_subscriptions_parent_user_id_fkey FOREIGN KEY (parent_user_id) REFERENCES public.users(user_id) ON DELETE CASCADE;


--
-- Name: sub_account_subscriptions sub_account_subscriptions_sub_user_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.sub_account_subscriptions
    ADD CONSTRAINT sub_account_subscriptions_sub_user_id_fkey FOREIGN KEY (sub_user_id) REFERENCES public.users(user_id) ON DELETE CASCADE;


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
-- Name: user_pair_accounts user_pair_accounts_account_a_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.user_pair_accounts
    ADD CONSTRAINT user_pair_accounts_account_a_id_fkey FOREIGN KEY (account_a_id) REFERENCES public.accounts(account_id) ON DELETE SET NULL;


--
-- Name: user_pair_accounts user_pair_accounts_account_b_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.user_pair_accounts
    ADD CONSTRAINT user_pair_accounts_account_b_id_fkey FOREIGN KEY (account_b_id) REFERENCES public.accounts(account_id) ON DELETE SET NULL;


--
-- Name: user_pair_accounts user_pair_accounts_user_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.user_pair_accounts
    ADD CONSTRAINT user_pair_accounts_user_id_fkey FOREIGN KEY (user_id) REFERENCES public.users(user_id) ON DELETE CASCADE;


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
-- Name: users users_parent_user_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.users
    ADD CONSTRAINT users_parent_user_id_fkey FOREIGN KEY (parent_user_id) REFERENCES public.users(user_id) ON DELETE CASCADE;


--
-- Name: SCHEMA public; Type: ACL; Schema: -; Owner: postgres
--

REVOKE USAGE ON SCHEMA public FROM PUBLIC;


--
-- PostgreSQL database dump complete
--

\unrestrict MWKwDyrs9TGgCqSggX18wf5A79ypOpAGQSrqwxKgmgwRMl7Mh0rxIB8EFhdQAqM

