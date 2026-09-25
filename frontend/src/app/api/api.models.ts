export interface Region {
  region_id: number;
  code: string;
  display_name: string;
}

export interface RegionsResponse {
  regions: Region[];
}

export interface CreateCaseRequest {
  anonymous_patient_code: string;
}

export interface CaseResponse {
  case_id: string;
  anonymous_patient_code: string;
  created_at: string;
}

export interface ImageResponse {
  image_id: string;
  case_id: string;
  width: number;
  height: number;
  sha256: string;
  created_at: string;
}

export interface CreateEvaluationRequest {
  pci_region_id: number;
  annotator_code: string;
}

export interface EvaluationResponse {
  evaluation_id: string;
  image_id: string;
  pci_region_id: number;
  annotator_code: string;
  status: 'draft' | 'finalized';
  clinical_ls: number | null;
  annotator_confidence: number | null;
  created_at: string;
  finalized_at: string | null;
}

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
