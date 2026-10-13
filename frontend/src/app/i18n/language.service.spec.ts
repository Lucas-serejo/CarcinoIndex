import { provideHttpClient } from '@angular/common/http';
import { HttpTestingController, provideHttpClientTesting } from '@angular/common/http/testing';
import { TestBed } from '@angular/core/testing';
import { App } from '../app.component';
import { LanguageService } from './language.service';

describe('Presentation language', () => {
  it('starts in Portuguese and switches through native header buttons without rechecking health', () => {
    TestBed.configureTestingModule({ imports: [App], providers: [provideHttpClient(), provideHttpClientTesting()] });
    const fixture = TestBed.createComponent(App);
    const http = TestBed.inject(HttpTestingController);
    fixture.detectChanges();
    const element: HTMLElement = fixture.nativeElement;
    expect(document.documentElement.lang).toBe('pt-BR');
    expect(element.textContent).toContain('Segmentação assistida.');
    expect(element.textContent).toContain('Verificando…');
    http.expectOne('/health').flush({ status: 'ok', model: { loaded: true, name: 'sam2.1_hiera_small', device: 'cpu', dtype: 'float32' } });
    fixture.detectChanges();
    const health = fixture.componentInstance.health();
    element.querySelector<HTMLButtonElement>('.language-selector [lang="en"]')!.click();
    fixture.detectChanges();
    expect(document.documentElement.lang).toBe('en');
    expect(element.textContent).toContain('Assisted segmentation.');
    expect(element.querySelector('[lang="en"]')?.getAttribute('aria-pressed')).toBe('true');
    expect(fixture.componentInstance.health()).toBe(health);
    element.querySelector<HTMLButtonElement>('.language-selector [lang="pt-BR"]')!.click();
    fixture.detectChanges();
    expect(document.documentElement.lang).toBe('pt-BR');
    expect(element.textContent).toContain('Iniciar avaliação');
    http.verify();
    fixture.destroy();
  });

  it('translates presentation labels and errors without modifying canonical values', () => {
    const language = TestBed.inject(LanguageService);
    expect(language.text('Partially adequate')).toBe('Parcialmente adequada');
    expect(language.text('partially_adequate')).toBe('partially_adequate');
    expect(language.error('The request fields are invalid or incomplete.')).toContain('inválidos');
    expect(language.error('Unmapped backend detail.')).toBe('Unmapped backend detail.');
    language.select('en');
    expect(language.text('Partially adequate')).toBe('Partially adequate');
  });
});
