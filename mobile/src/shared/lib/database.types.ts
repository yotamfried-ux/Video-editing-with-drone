export type Json =
  | string
  | number
  | boolean
  | null
  | { [key: string]: Json | undefined }
  | Json[]

export interface Database {
  public: {
    Tables: {
      analytics_events: {
        Row: {
          created_at: string | null
          event_type: string
          id: string
          payment_id: string | null
          recording_date: string | null
          reel_id: string | null
          revenue_ils: number | null
          sport: string | null
        }
      }
      athlete_profiles: {
        Row: {
          created_at: string | null
          email: string
          id: string
          name: string | null
          push_token: string | null
          user_id: string | null
        }
      }
      payments: {
        Row: {
          amount_ils: number | null
          created_at: string | null
          download_token: string
          id: string
          meshulam_transaction_id: string | null
          paid_at: string | null
          reel_id: string | null
          status: string | null
          stripe_payment_intent_id: string | null
        }
      }
      pipeline_status: {
        Row: {
          id: number
          meta: Json | null
          progress: number | null
          stage: string | null
          updated_at: string | null
        }
      }
      pricing: {
        Row: { price_ils: number; price_unit: 'major_ils_v1'; sport: string; updated_at: string | null }
      }
      reels: {
        Row: {
          athlete_desc: string | null
          created_at: string | null
          expires_at: string | null
          id: string
          recording_date: string | null
          source_video: string | null
          sport: string | null
          status: string | null
          storage_path: string | null
          stream_uid: string | null
          token: string | null
        }
      }
      suggestions: {
        Row: {
          created_at: string | null
          id: string
          message: string
          reel_id: string | null
          user_id: string | null
        }
      }
      support_tickets: {
        Row: {
          created_at: string | null
          id: string
          message: string
          operator_reply: string | null
          reel_id: string | null
          replied_at: string | null
          status: string | null
          user_id: string | null
        }
      }
    }
  }
}
