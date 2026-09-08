-- Migration 017: Create support_conversations and support_tickets tables.
--
-- Stores in-app AI support chat sessions (with turn counters and escalation
-- state) and persisted email-escalation tickets created when a conversation
-- exceeds the automated assistant turn limit or the user explicitly requests
-- human support.

CREATE TABLE IF NOT EXISTS support_conversations (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  user_id UUID REFERENCES profiles(id) ON DELETE CASCADE,
  user_email TEXT NOT NULL,
  turn_count INTEGER DEFAULT 0,
  is_escalated BOOLEAN DEFAULT FALSE,
  created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_support_conversations_user_id
  ON support_conversations (user_id);

CREATE INDEX IF NOT EXISTS idx_support_conversations_escalated
  ON support_conversations (is_escalated);

CREATE TABLE IF NOT EXISTS support_tickets (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  user_id UUID REFERENCES profiles(id) ON DELETE CASCADE,
  user_email TEXT NOT NULL,
  subject TEXT NOT NULL,
  conversation_summary TEXT NOT NULL,
  transcript JSONB NOT NULL,
  status TEXT DEFAULT 'open',  -- 'open', 'resolved', 'in_progress'
  created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_support_tickets_user_id
  ON support_tickets (user_id);

CREATE INDEX IF NOT EXISTS idx_support_tickets_status
  ON support_tickets (status);
