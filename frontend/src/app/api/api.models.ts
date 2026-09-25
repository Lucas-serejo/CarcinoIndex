export interface ModelHealth {
  loaded: boolean;
  name: string;
  device: string;
  dtype: string;
}

export interface HealthResponse {
  status: 'ok';
  model: ModelHealth;
}

export interface ApiErrorResponse {
  error: {
    code: string;
    message: string;
  };
}
