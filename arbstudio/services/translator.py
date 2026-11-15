"""Claude API ile toplu makine çevirisi.

Bu modül Qt'den bağımsızdır — arayüz katmanı `translate_batches()` üzerinde
bir QThread çalıştırır. Hiçbir şey doğrudan projeye yazılmaz; sonuçlar öneri
olarak döner, kullanıcı önizlemede onaylar.

Model seçimi ve istek biçimi Anthropic Messages API'sinin güncel sözleşmesine
göre: yapılandırılmış çıktı (`output_config.format`) sayesinde yanıt her zaman
şemaya uyan geçerli JSON olur; ayrıştırma sırasında serbest metin ayıklamaya
gerek kalmaz.
"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass, field
from typing import Callable, Dict, List, Optional, Sequence

from ..model.keyinfo import placeholders
from ..model.project import KeyRef, Project

#: Varsayılan model. Daha ucuz alternatif olarak `claude-sonnet-5` seçilebilir.
DEFAULT_MODEL = "claude-opus-5"
AVAILABLE_MODELS = [
    ("claude-opus-5", "Claude Opus 5 — en yüksek kalite"),
    ("claude-sonnet-5", "Claude Sonnet 5 — daha ucuz/hızlı"),
    ("claude-haiku-4-5", "Claude Haiku 4.5 — en ucuz, kısa metinler için"),
]

#: Tek istekte gönderilecek anahtar sayısı.
DEFAULT_BATCH_SIZE = 40

ENV_KEY = "ANTHROPIC_API_KEY"

#: Yanıt şeması — API'nin bu yapıya uyan JSON döndürmesi garanti edilir.
RESPONSE_SCHEMA = {
    "type": "object",
    "properties": {
        "translations": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "id": {"type": "integer"},
                    "text": {"type": "string"},
                },
                "required": ["id", "text"],
                "additionalProperties": False,
            },
        }
    },
    "required": ["translations"],
    "additionalProperties": False,
}

SYSTEM_PROMPT = """Sen bir mobil İslami uygulamanın (namaz vakitleri, Kur'an okuyucu,
zekat/miras hesaplayıcıları, kütüphane, quiz) arayüz metinlerini çeviren uzman bir
yerelleştirme çevirmenisin.

Kurallar:
- Yalnızca kullanıcı arayüzü metni çevir. Kısa, doğal ve o dilde alışılmış terimleri kullan.
- {count} ve {name} gibi süslü parantezli yer tutucuları AYNEN koru — adlarını çevirme,
  silme, ekleme yapma. Konumlarını hedef dilin dizilimine göre değiştirebilirsin.
- Satır sonlarını (\\n) ve baştaki/sondaki boşlukları kaynaktaki gibi bırak.
- Uzunluğu kaynağa yakın tut; butonlar ve etiketler dar alanlara sığmalı.
- Dinî terimleri (namaz, abdest, zekat, kıble, hadis, sure, ayet) hedef dilde
  Müslüman topluluğun kullandığı yerleşik karşılıklarıyla ver.
- Ham metni döndür: tırnak ekleme, açıklama yazma, biçimlendirme uygulama.
- Bir girdiyi çeviremezsen bile mutlaka bir çeviri döndür; hiçbir id'yi atlama."""


@dataclass
class Suggestion:
    ref: KeyRef
    source: str
    current: str
    proposed: str
    placeholder_issue: str = ""

    @property
    def is_valid(self) -> bool:
        return not self.placeholder_issue


@dataclass
class TranslationResult:
    suggestions: List[Suggestion] = field(default_factory=list)
    errors: List[str] = field(default_factory=list)
    input_tokens: int = 0
    output_tokens: int = 0
    cancelled: bool = False

    @property
    def invalid_count(self) -> int:
        return sum(1 for item in self.suggestions if not item.is_valid)


class TranslatorError(RuntimeError):
    pass


def resolve_api_key(stored: Optional[str] = None) -> Optional[str]:
    """Ortam değişkeni ayarlardaki anahtarın önüne geçer."""
    return os.environ.get(ENV_KEY) or (stored or None)


def language_name(code: str) -> str:
    names = {
        "tr": "Türkçe", "en": "İngilizce", "ar": "Arapça", "de": "Almanca",
        "fr": "Fransızca", "es": "İspanyolca", "ru": "Rusça", "fa": "Farsça",
        "ur": "Urduca", "id": "Endonezce", "ms": "Malayca", "bn": "Bengalce",
        "az": "Azerbaycanca", "ku": "Kürtçe", "sq": "Arnavutça", "bs": "Boşnakça",
        "nl": "Felemenkçe", "it": "İtalyanca", "pt": "Portekizce", "sw": "Svahili",
        "ha": "Hausa", "so": "Somalice", "uz": "Özbekçe", "kk": "Kazakça",
        "tt": "Tatarca", "hi": "Hintçe", "zh": "Çince", "ja": "Japonca",
        "ko": "Korece", "pl": "Lehçe", "sv": "İsveççe", "no": "Norveççe",
    }
    return names.get(code.split("_")[0], code)


def _build_client(api_key: str, max_retries: int = 3):
    try:
        import anthropic
    except ImportError as exc:  # pragma: no cover - kurulum sorunu
        raise TranslatorError(
            "'anthropic' paketi kurulu değil. Kurulum: pip install anthropic"
        ) from exc
    return anthropic.Anthropic(api_key=api_key, max_retries=max_retries, timeout=180.0)


def _batch_payload(project: Project, refs: Sequence[KeyRef]) -> List[dict]:
    items = []
    for index, ref in enumerate(refs):
        entry: dict = {"id": index, "key": ref.key, "text": project.source_value(ref)}
        names = sorted(placeholders(entry["text"]))
        if names:
            entry["placeholders"] = names
        items.append(entry)
    return items


def _check_placeholders(source: str, proposed: str) -> str:
    expected, actual = placeholders(source), placeholders(proposed)
    if expected == actual:
        return ""
    missing = sorted(expected - actual)
    extra = sorted(actual - expected)
    parts = []
    if missing:
        parts.append("eksik: " + ", ".join("{%s}" % n for n in missing))
    if extra:
        parts.append("fazla: " + ", ".join("{%s}" % n for n in extra))
    return "; ".join(parts)


def translate_batches(
    project: Project,
    refs: Sequence[KeyRef],
    target_lang: str,
    api_key: str,
    model: str = DEFAULT_MODEL,
    batch_size: int = DEFAULT_BATCH_SIZE,
    progress: Optional[Callable[[int, int, str], None]] = None,
    should_cancel: Optional[Callable[[], bool]] = None,
) -> TranslationResult:
    """Seçili anahtarları gruplar hâlinde çevirir; öneri listesi döndürür."""
    import anthropic

    result = TranslationResult()
    if not refs:
        return result

    client = _build_client(api_key)
    source_name = language_name(project.source_lang)
    target_name = language_name(target_lang)
    total = len(refs)
    done = 0

    for start in range(0, total, batch_size):
        if should_cancel is not None and should_cancel():
            result.cancelled = True
            break

        chunk = list(refs[start : start + batch_size])
        payload = _batch_payload(project, chunk)
        user_text = (
            f"Aşağıdaki {len(payload)} arayüz metnini {source_name} dilinden "
            f"{target_name} diline çevir. Her girdi için aynı id ile bir çeviri "
            f"döndür.\n\n"
            + json.dumps(payload, ensure_ascii=False, indent=1)
        )

        try:
            response = client.messages.create(
                model=model,
                max_tokens=16000,
                system=SYSTEM_PROMPT,
                output_config={
                    "effort": "low",
                    "format": {"type": "json_schema", "schema": RESPONSE_SCHEMA},
                },
                messages=[{"role": "user", "content": user_text}],
            )
        except anthropic.APIStatusError as exc:
            result.errors.append(
                f"Anahtar {start + 1}-{start + len(chunk)}: API hatası "
                f"({exc.status_code}) {exc.message}"
            )
            done += len(chunk)
            if progress:
                progress(done, total, "hata")
            continue
        except anthropic.APIConnectionError as exc:
            result.errors.append(
                f"Anahtar {start + 1}-{start + len(chunk)}: bağlantı hatası ({exc})"
            )
            done += len(chunk)
            if progress:
                progress(done, total, "hata")
            continue

        result.input_tokens += response.usage.input_tokens
        result.output_tokens += response.usage.output_tokens

        if response.stop_reason == "refusal":
            result.errors.append(
                f"Anahtar {start + 1}-{start + len(chunk)}: model bu içeriği çevirmeyi reddetti"
            )
            done += len(chunk)
            if progress:
                progress(done, total, "reddedildi")
            continue

        text = next((b.text for b in response.content if b.type == "text"), "")
        try:
            data = json.loads(text)
            translations = data["translations"]
        except (ValueError, KeyError, TypeError) as exc:
            result.errors.append(
                f"Anahtar {start + 1}-{start + len(chunk)}: yanıt ayrıştırılamadı ({exc})"
            )
            done += len(chunk)
            if progress:
                progress(done, total, "hata")
            continue

        by_id: Dict[int, str] = {}
        for item in translations:
            if isinstance(item, dict) and isinstance(item.get("id"), int):
                by_id[item["id"]] = str(item.get("text", ""))

        for index, ref in enumerate(chunk):
            proposed = by_id.get(index)
            if proposed is None:
                result.errors.append(f"'{ref.key}' için çeviri dönmedi")
                continue
            source = project.source_value(ref)
            result.suggestions.append(
                Suggestion(
                    ref=ref,
                    source=source,
                    current=project.value(ref, target_lang) or "",
                    proposed=proposed,
                    placeholder_issue=_check_placeholders(source, proposed),
                )
            )

        done += len(chunk)
        if progress:
            progress(done, total, f"{len(by_id)} çeviri alındı")

    return result


def estimate_cost(input_tokens: int, output_tokens: int, model: str) -> float:
    """Kaba maliyet tahmini (USD). Fiyatlar 1M token başınadır."""
    prices = {
        "claude-opus-5": (5.00, 25.00),
        "claude-sonnet-5": (3.00, 15.00),
        "claude-haiku-4-5": (1.00, 5.00),
    }
    per_in, per_out = prices.get(model, (5.00, 25.00))
    return input_tokens / 1_000_000 * per_in + output_tokens / 1_000_000 * per_out
