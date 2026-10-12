import { DOCUMENT, registerLocaleData } from '@angular/common';
import pt from '@angular/common/locales/pt';
import { inject, Injectable, signal } from '@angular/core';
import { ptBR } from './translations';

registerLocaleData(pt, 'pt-BR');

export type Language = 'pt-BR' | 'en';

@Injectable({ providedIn: 'root' })
export class LanguageService {
  private readonly document = inject(DOCUMENT);
  private readonly current = signal<Language>('pt-BR');
  readonly language = this.current.asReadonly();

  constructor() { this.select('pt-BR'); }

  select(language: Language): void {
    this.current.set(language);
    this.document.documentElement.lang = language;
    this.document.title = `CarcinoIndex | ${this.text('Research workspace')}`;
    this.document.querySelector('meta[name="description"]')?.setAttribute('content', language === 'pt-BR'
      ? 'Plataforma experimental para segmentação assistida de lesões em imagens laparoscópicas.'
      : 'Experimental platform for assisted segmentation of lesions in laparoscopic images.');
  }

  text(value: string | null | undefined): string {
    if (!value) return '';
    return this.language() === 'pt-BR' && Object.hasOwn(ptBR, value) ? ptBR[value] : value;
  }

  error(value: string | null | undefined): string {
    if (!value) return '';
    if (this.language() === 'en') return value;
    return Object.hasOwn(ptBR, value) ? ptBR[value] : value;
  }
}
