export interface StatisticsSummary {
  total_requests: number
  total_cost: number
  total_tokens: number
  online_time: number
  total_messages: number
  total_replies: number
  avg_response_time: number
  cost_per_hour: number
  tokens_per_hour: number
}

export interface LLMStatistics {
  request_count: number
  prompt_tokens: number
  completion_tokens: number
  total_tokens: number
  total_cost: number
  avg_response_time: number
}

export interface ModelStatistics extends LLMStatistics {
  model_name: string
}

export interface CategoryStatistics extends LLMStatistics {
  name: string
}

export interface ChatStatistics {
  chat_id: string
  chat_name: string
  message_count: number
}

export interface TimeSeriesData {
  timestamp: string
  requests: number
  cost: number
  tokens: number
}

export interface RecentActivity {
  timestamp: string
  model: string
  request_type: string
  tokens: number
  cost: number
  time_cost: number
  status: string
}

export interface StatisticsPeriod {
  start_time: string
  end_time: string
  hours: number
}

export interface StatisticsReport {
  period: StatisticsPeriod
  summary: StatisticsSummary
  model_stats: ModelStatistics[]
  module_stats: CategoryStatistics[]
  request_type_stats: CategoryStatistics[]
  chat_stats: ChatStatistics[]
  time_series: TimeSeriesData[]
  time_series_granularity: 'hour' | 'day'
  recent_activity: RecentActivity[]
}
