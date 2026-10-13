--
-- PostgreSQL database dump
--


-- Dumped from database version 16.10
-- Dumped by pg_dump version 16.10

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
-- Name: public; Type: SCHEMA; Schema: -; Owner: -
--

CREATE SCHEMA public;


--
-- Name: SCHEMA public; Type: COMMENT; Schema: -; Owner: -
--

COMMENT ON SCHEMA public IS 'standard public schema';


SET default_tablespace = '';

SET default_table_access_method = heap;

--
-- Name: agent_directory; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.agent_directory (
    agent_id character varying(36) NOT NULL,
    name character varying(100) NOT NULL,
    role character varying(100) NOT NULL,
    description text,
    capabilities jsonb,
    reports_to character varying(36),
    seniority_level integer,
    status character varying(20),
    created_at timestamp without time zone,
    updated_at timestamp without time zone,
    skills jsonb,
    usual_model character varying(100),
    join_date timestamp without time zone,
    birth_date timestamp without time zone,
    agent_type character varying(50) DEFAULT 'AI Agent'::character varying
);


--
-- Name: agent_sessions; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.agent_sessions (
    session_id character varying(36) NOT NULL,
    agent_id character varying(100) NOT NULL,
    started_at timestamp without time zone,
    ended_at timestamp without time zone,
    user_id character varying(100),
    current_focus character varying(255),
    summary_notes text,
    active_context_tags jsonb
);


--
-- Name: agent_skills; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.agent_skills (
    agent_id character varying(36) NOT NULL,
    skill_id character varying(36) NOT NULL,
    created_at timestamp without time zone
);


--
-- Name: agent_tasks; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.agent_tasks (
    task_id character varying(36) NOT NULL,
    title character varying(255) NOT NULL,
    description text,
    assigned_to_agent character varying(100) NOT NULL,
    created_by_agent character varying(100) NOT NULL,
    status character varying(50) NOT NULL,
    priority integer,
    linked_project character varying(255),
    summary_notes text,
    due_date timestamp without time zone,
    created_at timestamp without time zone,
    updated_at timestamp without time zone
);


--
-- Name: api_keys; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.api_keys (
    key_id character varying(36) NOT NULL,
    api_key character varying(64) NOT NULL,
    name character varying(100) NOT NULL,
    description text,
    created_at timestamp without time zone,
    last_used_at timestamp without time zone,
    expires_at timestamp without time zone,
    is_active boolean,
    rate_limit integer,
    total_requests integer
);


--
-- Name: api_request_logs; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.api_request_logs (
    log_id character varying(36) NOT NULL,
    api_key_id character varying(36),
    "timestamp" timestamp without time zone,
    ip_address character varying(45),
    endpoint character varying(255) NOT NULL,
    method character varying(10) NOT NULL,
    status_code integer,
    user_agent character varying(255),
    request_data text
);


--
-- Name: decision_log; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.decision_log (
    decision_id character varying(36) NOT NULL,
    context character varying(255) NOT NULL,
    made_by_agent character varying(100) NOT NULL,
    "timestamp" timestamp without time zone,
    decision_text text NOT NULL,
    impact_area character varying(255),
    reversal_possible boolean
);


--
-- Name: experiments; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.experiments (
    experiment_id character varying(36) NOT NULL,
    title character varying(255) NOT NULL,
    description text,
    hypothesis text NOT NULL,
    executing_agent character varying(100) NOT NULL,
    outcome text,
    notes text,
    status character varying(50) NOT NULL,
    created_at timestamp without time zone,
    updated_at timestamp without time zone
);


--
-- Name: gpt_messages; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.gpt_messages (
    message_id character varying(36) NOT NULL,
    sender_agent character varying(100) NOT NULL,
    receiver_agent character varying(100),
    "timestamp" timestamp without time zone,
    message_type character varying(50) NOT NULL,
    content text NOT NULL,
    session_id character varying(36)
);


--
-- Name: invitation_tokens; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.invitation_tokens (
    id character varying(36) NOT NULL,
    token character varying(64) NOT NULL,
    email_hint character varying(120),
    created_by character varying(36) NOT NULL,
    created_at timestamp without time zone,
    expires_at timestamp without time zone NOT NULL,
    used_at timestamp without time zone,
    used_by character varying(36)
);


--
-- Name: kb_index; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.kb_index (
    index_id character varying(36) NOT NULL,
    term character varying(255) NOT NULL,
    defined_by_file character varying(255),
    used_by_agents jsonb,
    relevance_score integer,
    last_verified timestamp without time zone,
    synonyms jsonb,
    created_at timestamp without time zone,
    updated_at timestamp without time zone
);


--
-- Name: memory_links; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.memory_links (
    link_id character varying(36) NOT NULL,
    pinecone_vector_id character varying(36) NOT NULL,
    summary text,
    linked_agent_event character varying(36),
    origin_file_or_source character varying(255),
    timestamp_added timestamp without time zone
);


--
-- Name: org_profile; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.org_profile (
    id integer NOT NULL,
    org_name character varying(128),
    logo character varying(255),
    website character varying(255),
    contact_email character varying(120),
    phone character varying(32),
    description text,
    city character varying(64),
    state character varying(64),
    country character varying(64),
    linkedin character varying(255),
    twitter character varying(255),
    facebook character varying(255),
    instagram character varying(255),
    updated_at timestamp without time zone
);


--
-- Name: org_state; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.org_state (
    entity_id character varying(36) NOT NULL,
    entity character varying(255) NOT NULL,
    type character varying(50) NOT NULL,
    status character varying(50) NOT NULL,
    summary text,
    owner_agent character varying(100) NOT NULL,
    last_updated_by character varying(100) NOT NULL,
    important_dates jsonb,
    linked_docs jsonb,
    created_at timestamp without time zone,
    updated_at timestamp without time zone
);


--
-- Name: project_decisions; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.project_decisions (
    id character varying(36) NOT NULL,
    gpt_role character varying(100) NOT NULL,
    decision_text text NOT NULL,
    context_embedding json NOT NULL,
    related_documents json NOT NULL,
    "timestamp" timestamp without time zone
);


--
-- Name: resources; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.resources (
    id character varying(36) NOT NULL,
    name character varying(255) NOT NULL,
    type character varying(32) NOT NULL,
    purpose text,
    url character varying(512),
    poc_type character varying(32) NOT NULL,
    related_skills text,
    description text,
    created_by character varying(36),
    created_at timestamp without time zone,
    updated_at timestamp without time zone
);


--
-- Name: shared_contexts; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.shared_contexts (
    id character varying(36) NOT NULL,
    sender character varying(100) NOT NULL,
    recipients json NOT NULL,
    context_tag character varying(100) NOT NULL,
    memory_refs json NOT NULL,
    "timestamp" timestamp without time zone
);


--
-- Name: skill_files; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.skill_files (
    id character varying(36) NOT NULL,
    skill_id character varying(36) NOT NULL,
    filename character varying(255) NOT NULL,
    stored_filename character varying(255) NOT NULL,
    uploaded_at timestamp without time zone
);


--
-- Name: skills; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.skills (
    id character varying(36) NOT NULL,
    name character varying(255) NOT NULL,
    type character varying(32) NOT NULL,
    source text,
    description text,
    poc_type character varying(32) NOT NULL,
    created_by character varying(36),
    created_at timestamp without time zone,
    updated_at timestamp without time zone
);


--
-- Name: unstructured_data; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.unstructured_data (
    id character varying(36) NOT NULL,
    content text NOT NULL,
    pinecone_id character varying(36) NOT NULL
);


--
-- Name: user_insights; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.user_insights (
    insight_id character varying(36) NOT NULL,
    user_id character varying(100) NOT NULL,
    interaction_type character varying(100) NOT NULL,
    summary text NOT NULL,
    "timestamp" timestamp without time zone,
    related_agent_or_project character varying(255),
    result text,
    tone_tag character varying(50)
);


--
-- Name: user_skills; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.user_skills (
    user_id character varying(36) NOT NULL,
    skill_id character varying(36) NOT NULL,
    created_at timestamp without time zone
);


--
-- Name: users; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.users (
    id character varying(36) NOT NULL,
    username character varying(64) NOT NULL,
    email character varying(120) NOT NULL,
    password_hash character varying(256) NOT NULL,
    role character varying(20) NOT NULL,
    is_active boolean NOT NULL,
    created_at timestamp without time zone,
    first_name character varying(64),
    last_name character varying(64),
    company_name character varying(128),
    phone character varying(32),
    whatsapp character varying(32),
    signal character varying(32),
    telegram character varying(64),
    website character varying(255),
    profile_image character varying(255)
);


--
-- Name: waitlist; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.waitlist (
    id integer NOT NULL,
    first_name character varying(100) NOT NULL,
    email character varying(120) NOT NULL,
    created_at timestamp without time zone
);


--
-- Name: waitlist_id_seq1; Type: SEQUENCE; Schema: public; Owner: -
--

CREATE SEQUENCE public.waitlist_id_seq1
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


--
-- Name: waitlist_id_seq1; Type: SEQUENCE OWNED BY; Schema: public; Owner: -
--

ALTER SEQUENCE public.waitlist_id_seq1 OWNED BY public.waitlist.id;


--
-- Name: waitlist id; Type: DEFAULT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.waitlist ALTER COLUMN id SET DEFAULT nextval('public.waitlist_id_seq1'::regclass);


--
-- Name: agent_directory agent_directory_name_key; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.agent_directory
    ADD CONSTRAINT agent_directory_name_key UNIQUE (name);


--
-- Name: agent_directory agent_directory_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.agent_directory
    ADD CONSTRAINT agent_directory_pkey PRIMARY KEY (agent_id);


--
-- Name: agent_sessions agent_sessions_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.agent_sessions
    ADD CONSTRAINT agent_sessions_pkey PRIMARY KEY (session_id);


--
-- Name: agent_skills agent_skills_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.agent_skills
    ADD CONSTRAINT agent_skills_pkey PRIMARY KEY (agent_id, skill_id);


--
-- Name: agent_tasks agent_tasks_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.agent_tasks
    ADD CONSTRAINT agent_tasks_pkey PRIMARY KEY (task_id);


--
-- Name: api_keys api_keys_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.api_keys
    ADD CONSTRAINT api_keys_pkey PRIMARY KEY (key_id);


--
-- Name: api_request_logs api_request_logs_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.api_request_logs
    ADD CONSTRAINT api_request_logs_pkey PRIMARY KEY (log_id);


--
-- Name: decision_log decision_log_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.decision_log
    ADD CONSTRAINT decision_log_pkey PRIMARY KEY (decision_id);


--
-- Name: experiments experiments_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.experiments
    ADD CONSTRAINT experiments_pkey PRIMARY KEY (experiment_id);


--
-- Name: gpt_messages gpt_messages_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.gpt_messages
    ADD CONSTRAINT gpt_messages_pkey PRIMARY KEY (message_id);


--
-- Name: invitation_tokens invitation_tokens_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.invitation_tokens
    ADD CONSTRAINT invitation_tokens_pkey PRIMARY KEY (id);


--
-- Name: kb_index kb_index_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.kb_index
    ADD CONSTRAINT kb_index_pkey PRIMARY KEY (index_id);


--
-- Name: memory_links memory_links_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.memory_links
    ADD CONSTRAINT memory_links_pkey PRIMARY KEY (link_id);


--
-- Name: org_profile org_profile_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.org_profile
    ADD CONSTRAINT org_profile_pkey PRIMARY KEY (id);


--
-- Name: org_state org_state_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.org_state
    ADD CONSTRAINT org_state_pkey PRIMARY KEY (entity_id);


--
-- Name: project_decisions project_decisions_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.project_decisions
    ADD CONSTRAINT project_decisions_pkey PRIMARY KEY (id);


--
-- Name: resources resources_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.resources
    ADD CONSTRAINT resources_pkey PRIMARY KEY (id);


--
-- Name: shared_contexts shared_contexts_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.shared_contexts
    ADD CONSTRAINT shared_contexts_pkey PRIMARY KEY (id);


--
-- Name: skill_files skill_files_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.skill_files
    ADD CONSTRAINT skill_files_pkey PRIMARY KEY (id);


--
-- Name: skills skills_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.skills
    ADD CONSTRAINT skills_pkey PRIMARY KEY (id);


--
-- Name: unstructured_data unstructured_data_pinecone_id_key; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.unstructured_data
    ADD CONSTRAINT unstructured_data_pinecone_id_key UNIQUE (pinecone_id);


--
-- Name: unstructured_data unstructured_data_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.unstructured_data
    ADD CONSTRAINT unstructured_data_pkey PRIMARY KEY (id);


--
-- Name: user_insights user_insights_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.user_insights
    ADD CONSTRAINT user_insights_pkey PRIMARY KEY (insight_id);


--
-- Name: user_skills user_skills_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.user_skills
    ADD CONSTRAINT user_skills_pkey PRIMARY KEY (user_id, skill_id);


--
-- Name: users users_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.users
    ADD CONSTRAINT users_pkey PRIMARY KEY (id);


--
-- Name: waitlist waitlist_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.waitlist
    ADD CONSTRAINT waitlist_pkey PRIMARY KEY (id);


--
-- Name: idx_unstructured_data_pinecone_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_unstructured_data_pinecone_id ON public.unstructured_data USING btree (pinecone_id);


--
-- Name: ix_agent_sessions_agent_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_agent_sessions_agent_id ON public.agent_sessions USING btree (agent_id);


--
-- Name: ix_agent_sessions_user_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_agent_sessions_user_id ON public.agent_sessions USING btree (user_id);


--
-- Name: ix_agent_tasks_assigned_to_agent; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_agent_tasks_assigned_to_agent ON public.agent_tasks USING btree (assigned_to_agent);


--
-- Name: ix_agent_tasks_linked_project; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_agent_tasks_linked_project ON public.agent_tasks USING btree (linked_project);


--
-- Name: ix_agent_tasks_status; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_agent_tasks_status ON public.agent_tasks USING btree (status);


--
-- Name: ix_api_keys_api_key; Type: INDEX; Schema: public; Owner: -
--

CREATE UNIQUE INDEX ix_api_keys_api_key ON public.api_keys USING btree (api_key);


--
-- Name: ix_api_request_logs_api_key_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_api_request_logs_api_key_id ON public.api_request_logs USING btree (api_key_id);


--
-- Name: ix_api_request_logs_timestamp; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_api_request_logs_timestamp ON public.api_request_logs USING btree ("timestamp");


--
-- Name: ix_decision_log_made_by_agent; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_decision_log_made_by_agent ON public.decision_log USING btree (made_by_agent);


--
-- Name: ix_decision_log_timestamp; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_decision_log_timestamp ON public.decision_log USING btree ("timestamp");


--
-- Name: ix_experiments_executing_agent; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_experiments_executing_agent ON public.experiments USING btree (executing_agent);


--
-- Name: ix_experiments_status; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_experiments_status ON public.experiments USING btree (status);


--
-- Name: ix_gpt_messages_receiver_agent; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_gpt_messages_receiver_agent ON public.gpt_messages USING btree (receiver_agent);


--
-- Name: ix_gpt_messages_sender_agent; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_gpt_messages_sender_agent ON public.gpt_messages USING btree (sender_agent);


--
-- Name: ix_gpt_messages_timestamp; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_gpt_messages_timestamp ON public.gpt_messages USING btree ("timestamp");


--
-- Name: ix_invitation_tokens_token; Type: INDEX; Schema: public; Owner: -
--

CREATE UNIQUE INDEX ix_invitation_tokens_token ON public.invitation_tokens USING btree (token);


--
-- Name: ix_kb_index_term; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_kb_index_term ON public.kb_index USING btree (term);


--
-- Name: ix_org_state_entity; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_org_state_entity ON public.org_state USING btree (entity);


--
-- Name: ix_org_state_owner_agent; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_org_state_owner_agent ON public.org_state USING btree (owner_agent);


--
-- Name: ix_org_state_status; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_org_state_status ON public.org_state USING btree (status);


--
-- Name: ix_org_state_type; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_org_state_type ON public.org_state USING btree (type);


--
-- Name: ix_skill_files_skill_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_skill_files_skill_id ON public.skill_files USING btree (skill_id);


--
-- Name: ix_user_insights_timestamp; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_user_insights_timestamp ON public.user_insights USING btree ("timestamp");


--
-- Name: ix_user_insights_user_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_user_insights_user_id ON public.user_insights USING btree (user_id);


--
-- Name: ix_users_email; Type: INDEX; Schema: public; Owner: -
--

CREATE UNIQUE INDEX ix_users_email ON public.users USING btree (email);


--
-- Name: ix_users_username; Type: INDEX; Schema: public; Owner: -
--

CREATE UNIQUE INDEX ix_users_username ON public.users USING btree (username);


--
-- Name: agent_directory agent_directory_reports_to_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.agent_directory
    ADD CONSTRAINT agent_directory_reports_to_fkey FOREIGN KEY (reports_to) REFERENCES public.agent_directory(agent_id);


--
-- Name: agent_skills agent_skills_agent_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.agent_skills
    ADD CONSTRAINT agent_skills_agent_id_fkey FOREIGN KEY (agent_id) REFERENCES public.agent_directory(agent_id) ON DELETE CASCADE;


--
-- Name: agent_skills agent_skills_skill_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.agent_skills
    ADD CONSTRAINT agent_skills_skill_id_fkey FOREIGN KEY (skill_id) REFERENCES public.skills(id) ON DELETE CASCADE;


--
-- Name: gpt_messages gpt_messages_session_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.gpt_messages
    ADD CONSTRAINT gpt_messages_session_id_fkey FOREIGN KEY (session_id) REFERENCES public.agent_sessions(session_id);


--
-- Name: invitation_tokens invitation_tokens_created_by_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.invitation_tokens
    ADD CONSTRAINT invitation_tokens_created_by_fkey FOREIGN KEY (created_by) REFERENCES public.users(id);


--
-- Name: invitation_tokens invitation_tokens_used_by_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.invitation_tokens
    ADD CONSTRAINT invitation_tokens_used_by_fkey FOREIGN KEY (used_by) REFERENCES public.users(id);


--
-- Name: memory_links memory_links_pinecone_vector_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.memory_links
    ADD CONSTRAINT memory_links_pinecone_vector_id_fkey FOREIGN KEY (pinecone_vector_id) REFERENCES public.unstructured_data(pinecone_id);


--
-- Name: resources resources_created_by_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.resources
    ADD CONSTRAINT resources_created_by_fkey FOREIGN KEY (created_by) REFERENCES public.users(id) ON DELETE SET NULL;


--
-- Name: skill_files skill_files_skill_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.skill_files
    ADD CONSTRAINT skill_files_skill_id_fkey FOREIGN KEY (skill_id) REFERENCES public.skills(id) ON DELETE CASCADE;


--
-- Name: skills skills_created_by_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.skills
    ADD CONSTRAINT skills_created_by_fkey FOREIGN KEY (created_by) REFERENCES public.users(id) ON DELETE SET NULL;


--
-- Name: user_skills user_skills_skill_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.user_skills
    ADD CONSTRAINT user_skills_skill_id_fkey FOREIGN KEY (skill_id) REFERENCES public.skills(id) ON DELETE CASCADE;


--
-- Name: user_skills user_skills_user_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.user_skills
    ADD CONSTRAINT user_skills_user_id_fkey FOREIGN KEY (user_id) REFERENCES public.users(id) ON DELETE CASCADE;


--
-- PostgreSQL database dump complete
--


