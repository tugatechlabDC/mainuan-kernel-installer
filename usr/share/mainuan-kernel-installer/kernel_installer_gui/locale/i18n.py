"""
Internationalization (i18n) support using gettext.
Provides _() function for translatable strings.
"""

import gettext
import locale
import os
from pathlib import Path

# Application domain
DOMAIN = "kernel-installer"

# Locale directory (relative to package)
LOCALE_DIR = Path(__file__).parent.parent / "locale"

# System locale directories to search
SYSTEM_LOCALE_DIRS = [
    Path("/usr/share/locale"),
    Path("/usr/local/share/locale"),
    Path.home() / ".local/share/locale",
]

# Current translation instance
_translation = None


def _normalize(code: str) -> str:
    """'pt_PT.UTF-8@euro' / 'pt-PT' -> 'pt_PT'. Returns '' for C / POSIX."""
    code = code.strip().split('.')[0].split('@')[0].replace('-', '_')
    if code in ('', 'C', 'POSIX'):
        return ''
    parts = code.split('_')
    return parts[0].lower() + (('_' + parts[1].upper()) if len(parts) > 1 and parts[1] else '')


def _system_locales() -> list:
    """
    System language preferences, most important first. Follows the same order
    as gettext: LANGUAGE, LC_ALL, LC_MESSAGES, LANG; then GLib / Python locale.
    """
    candidates = []
    for var in ('LANGUAGE', 'LC_ALL', 'LC_MESSAGES', 'LANG'):
        value = os.environ.get(var)
        if value:
            candidates.extend(value.split(':') if var == 'LANGUAGE' else [value])
    try:
        from gi.repository import GLib
        candidates.extend(GLib.get_language_names())
    except Exception:
        pass
    try:
        candidates.append(locale.getlocale()[0] or '')
    except Exception:
        pass
    result = []
    for c in candidates:
        n = _normalize(c)
        if n and n not in result:
            result.append(n)
    return result


def _available_dirs() -> set:
    """Names of the translation folders shipped with the application."""
    names = set()
    for d in [LOCALE_DIR] + SYSTEM_LOCALE_DIRS:
        try:
            for sub in d.iterdir():
                if (sub / "LC_MESSAGES" / f"{DOMAIN}.mo").exists():
                    names.add(sub.name)
        except Exception:
            continue
    return names


def resolve_language(candidates: list, available: set):
    """
    Pick the translation folder for the first usable system language.
    
    Returns (folder, found): folder is e.g. 'pt_PT', or None for English
    (the source language, needs no catalogue).
    
    Portuguese: pt_BR -> Brazilian; pt_PT and other Portuguese regions
    (pt_AO, pt_MZ...) -> European; plain 'pt' -> Brazilian.
    """
    for cand in candidates:
        lang, _sep, region = cand.partition('_')
        if lang == 'en':
            return None
        if lang == 'pt':
            if region == 'BR' or not region:
                target = 'pt_BR'
            else:
                target = 'pt_PT'
            if target in available:
                return target
            continue
        if cand in available:
            return cand
        if lang in available:
            return lang
    return None


def init_i18n(language: str = None) -> None:
    """
    Initialize internationalization.
    
    The language is detected automatically from the system locale. The optional
    ``language`` argument exists only for tests / debugging (never shown in the UI).
    """
    global _translation
    
    available = _available_dirs()
    candidates = [_normalize(language)] if language else _system_locales()
    chosen = resolve_language([c for c in candidates if c], available)
    
    if chosen:
        for locale_dir in [LOCALE_DIR] + SYSTEM_LOCALE_DIRS:
            try:
                _translation = gettext.translation(
                    DOMAIN, localedir=str(locale_dir), languages=[chosen], fallback=False)
                return
            except (FileNotFoundError, OSError):
                continue
    
    # English (source strings) or no catalogue found
    _translation = gettext.NullTranslations()


def _(message: str) -> str:
    """
    Translate a string.
    
    Use this function to wrap all user-visible strings:
        _("Hello, world!")
    
    Args:
        message: The string to translate
        
    Returns:
        Translated string, or original if no translation available
    """
    global _translation
    
    if _translation is None:
        init_i18n()
    
    return _translation.gettext(message)


def ngettext(singular: str, plural: str, n: int) -> str:
    """
    Translate a string with plural forms.
    
    Args:
        singular: Singular form
        plural: Plural form
        n: Count
        
    Returns:
        Appropriate translated form
    """
    global _translation
    
    if _translation is None:
        init_i18n()
    
    return _translation.ngettext(singular, plural, n)


def get_available_languages() -> list[str]:
    """Get list of available translations."""
    available = ['en']  # English is always available (fallback)
    
    for locale_dir in [LOCALE_DIR] + SYSTEM_LOCALE_DIRS:
        if locale_dir.exists():
            for lang_dir in locale_dir.iterdir():
                if lang_dir.is_dir():
                    mo_path = lang_dir / "LC_MESSAGES" / f"{DOMAIN}.mo"
                    if mo_path.exists():
                        lang = lang_dir.name
                        if lang not in available:
                            available.append(lang)
    
    return sorted(available)
