import { HttpClient, HttpErrorResponse } from '@angular/common/http';
import { inject, Injectable } from '@angular/core';
import { catchError, from, map, mergeMap, Observable, throwError, timeout } from 'rxjs';
import {
  ApiErrorResponse, HealthResponse, RegionsResponse, CreateCaseRequest,
  CaseResponse, ImageResponse, CreateEvaluationRequest, EvaluationResponse, ImageBox, PersistedSegmentationResponse,
} from './api.models';

function mapApiError(error: unknown): Observable<never> {
  const body: unknown = error instanceof HttpErrorResponse ? error.error : undefined;
  if (body instanceof Blob) {
    return from(body.text().then((text): unknown => {
      try { return JSON.parse(text) as unknown; } catch { return undefined; }
    }, () => undefined)).pipe(mergeMap(mappedError));
  }
  return mappedError(body);
}

function mappedError(body: unknown): Observable<never> {
  const message = isApiErrorResponse(body)
    ? body.error.message
    : 'Unable to reach the backend. Check that it is running and try again.';
  return throwError(() => new Error(message));
}

function isApiErrorResponse(value: unknown): value is ApiErrorResponse {
  if (typeof value !== 'object' || value === null || !('error' in value))
    return false;
  const error = value.error;
  return (
    typeof error === 'object' &&
    error !== null &&
    'code' in error &&
    typeof error.code === 'string' &&
    'message' in error &&
    typeof error.message === 'string'
  );
}

@Injectable({ providedIn: 'root' })
export class ExperimentApiService {
  private readonly http = inject(HttpClient);

  getEvaluation(evaluationId: string): Observable<EvaluationResponse> {
    return this.http.get<EvaluationResponse>(`/api/v1/evaluations/${evaluationId}`)
      .pipe(catchError(mapApiError));
  }

  getImageContent(imageId: string): Observable<Blob> {
    return this.http.get(`/api/v1/images/${imageId}/content`, { responseType: 'blob' }).pipe(
      catchError(mapApiError),
      map(blob => {
        if (!['image/jpeg', 'image/png'].includes(blob.type)) {
          throw new Error('The persisted image is not a supported JPEG or PNG.');
        }
        return blob;
      }),
    );
  }

  createBoxSegmentationAttempt(evaluationId: string, box: ImageBox): Observable<PersistedSegmentationResponse> {
    const body = new FormData();
    body.append('prompt_type', 'box');
    body.append('box', JSON.stringify([box.xMin, box.yMin, box.xMax, box.yMax]));
    body.append('multimask_output', 'true');
    return this.http.post<PersistedSegmentationResponse>(`/api/v1/evaluations/${evaluationId}/segmentations`, body)
      .pipe(catchError(mapApiError));
  }

  getHealth(): Observable<HealthResponse> {
    return this.http.get<HealthResponse>('/health').pipe(
      timeout(10000),
      catchError(mapApiError),
    );
  }

  getRegions(): Observable<RegionsResponse> {
    return this.http.get<RegionsResponse>('/api/v1/pci/regions').pipe(catchError(mapApiError));
  }

  createCase(request: CreateCaseRequest): Observable<CaseResponse> {
    return this.http.post<CaseResponse>('/api/v1/cases', request).pipe(catchError(mapApiError));
  }

  uploadCaseImage(caseId: string, file: File): Observable<ImageResponse> {
    const body = new FormData();
    body.append('image', file);
    return this.http.post<ImageResponse>(`/api/v1/cases/${caseId}/images`, body)
      .pipe(catchError(mapApiError));
  }

  createEvaluation(imageId: string, request: CreateEvaluationRequest): Observable<EvaluationResponse> {
    return this.http.post<EvaluationResponse>(`/api/v1/images/${imageId}/evaluations`, request)
      .pipe(catchError(mapApiError));
  }
}
