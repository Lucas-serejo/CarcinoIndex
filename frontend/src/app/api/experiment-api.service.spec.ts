import { provideHttpClient } from '@angular/common/http';
import {
  HttpTestingController,
  provideHttpClientTesting,
} from '@angular/common/http/testing';
import { TestBed } from '@angular/core/testing';
import { firstValueFrom } from 'rxjs';
import { ExperimentApiService } from './experiment-api.service';
import { HealthResponse } from './api.models';

describe('ExperimentApiService', () => {
  let service: ExperimentApiService;
  let http: HttpTestingController;

  beforeEach(() => {
    TestBed.configureTestingModule({
      providers: [provideHttpClient(), provideHttpClientTesting()],
    });
    service = TestBed.inject(ExperimentApiService);
    http = TestBed.inject(HttpTestingController);
  });

  afterEach(() => {
    http.verify();
    vi.useRealTimers();
  });

  it('loads PCI regions from the relative backend endpoint', async () => {
    const result = firstValueFrom(service.getRegions());
    const request = http.expectOne('/api/v1/pci/regions');
    expect(request.request.method).toBe('GET');
    request.flush({ regions: [] });
    expect(await result).toEqual({ regions: [] });
  });

  it('posts only the case contract', async () => {
    const body = { anonymous_patient_code: 'PATIENT-001' };
    const result = firstValueFrom(service.createCase(body));
    const request = http.expectOne('/api/v1/cases');
    expect(request.request.method).toBe('POST');
    expect(request.request.body).toEqual(body);
    request.flush({ case_id: 'case-1', ...body, created_at: '2026-09-25T12:00:00Z' });
    expect((await result).case_id).toBe('case-1');
  });

  it('uploads the exact selected File without forcing a multipart header', async () => {
    const file = new File(['image'], 'private-name.png', { type: 'image/png' });
    const result = firstValueFrom(service.uploadCaseImage('case-1', file));
    const request = http.expectOne('/api/v1/cases/case-1/images');
    expect(request.request.method).toBe('POST');
    expect(request.request.body).toBeInstanceOf(FormData);
    const body = request.request.body as FormData;
    expect([...body.keys()]).toEqual(['image']);
    expect(body.get('image')).toBe(file);
    expect(request.request.headers.has('Content-Type')).toBe(false);
    request.flush({ image_id: 'image-1' });
    expect((await result).image_id).toBe('image-1');
  });

  it('posts only region and annotator for a draft evaluation', async () => {
    const body = { pci_region_id: 0, annotator_code: 'MED01' };
    const result = firstValueFrom(service.createEvaluation('image-1', body));
    const request = http.expectOne('/api/v1/images/image-1/evaluations');
    expect(request.request.method).toBe('POST');
    expect(request.request.body).toEqual(body);
    request.flush({ evaluation_id: 'evaluation-1', ...body });
    expect((await result).evaluation_id).toBe('evaluation-1');
  });

  it('uses safe envelope mapping for lifecycle errors too', async () => {
    const result = firstValueFrom(service.createCase({ anonymous_patient_code: 'P01' }));
    const assertion = expect(result).rejects.toThrow('Could not create the clinical case.');
    http.expectOne('/api/v1/cases').flush(
      { error: { code: 'case_creation_failed', message: 'Could not create the clinical case.' } },
      { status: 500, statusText: 'Server Error' },
    );
    await assertion;
  });

  it('requests the relative health endpoint and preserves the backend response', async () => {
    const response: HealthResponse = {
      status: 'ok',
      model: {
        loaded: true,
        name: 'sam2.1_hiera_small',
        device: 'cpu',
        dtype: 'torch.float32',
      },
    };
    const result = firstValueFrom(service.getHealth());
    const request = http.expectOne('/health');
    expect(request.request.method).toBe('GET');
    request.flush(response);
    expect(await result).toEqual(response);
  });

  it('extracts a message from the documented backend error envelope', async () => {
    const result = firstValueFrom(service.getHealth());
    const assertion = expect(result).rejects.toThrow(
      'Segmentation service unavailable.',
    );
    http
      .expectOne('/health')
      .flush(
        {
          error: {
            code: 'service_unavailable',
            message: 'Segmentation service unavailable.',
          },
        },
        { status: 503, statusText: 'Unavailable' },
      );
    await assertion;
  });

  it.each([null, '<html>Bad gateway</html>', { error: { message: 42 } }])(
    'uses a fallback for unexpected error bodies: %j',
    async (body) => {
      const result = firstValueFrom(service.getHealth());
      const assertion = expect(result).rejects.toThrow(
        'Unable to reach the backend',
      );
      http
        .expectOne('/health')
        .flush(body, { status: 502, statusText: 'Bad Gateway' });
      await assertion;
    },
  );

  it('stops a stalled health request after ten seconds', async () => {
    vi.useFakeTimers();
    const result = firstValueFrom(service.getHealth());
    const assertion = expect(result).rejects.toThrow(
      'Unable to reach the backend',
    );
    const request = http.expectOne('/health');
    await vi.advanceTimersByTimeAsync(10000);
    await assertion;
    expect(request.cancelled).toBe(true);
  });
});
