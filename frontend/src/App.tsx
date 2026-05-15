import {
  Bot,
  Camera,
  FileText,
  LogOut,
  MessageSquare,
  Mic,
  Plus,
  Save,
  Send,
  Settings as SettingsIcon,
  Sparkles,
  Trash2,
  UploadCloud
} from "lucide-react";
import { ChangeEvent, FormEvent, useEffect, useMemo, useRef, useState } from "react";

import {
  Conversation,
  ConversationDetail,
  DocumentExtraction,
  DocumentFile,
  DocumentItem,
  OcrResult,
  OllamaModel,
  User,
  UserSettings,
  addDocumentFile,
  createConversation,
  deleteConversation,
  deleteDocument,
  deleteDocumentFile,
  getDocumentExtraction,
  getDocumentOcr,
  getConversation,
  getMe,
  getUserSettings,
  listConversations,
  listDocumentFiles,
  listDocuments,
  listModels,
  login,
  logout,
  register,
  runDocumentExtraction,
  runDocumentOcr,
  sendMessage,
  updateDocumentExtraction,
  updateUserSettings,
  uploadDocument
} from "./lib/api";

type AuthMode = "login" | "register";
type VoiceState = "idle" | "listening" | "recognizing" | "thinking" | "speaking" | "error";
type AppView = "chat" | "documents" | "settings";
type DocumentTextView = "overview" | "structured" | "raw" | "ocr";
type JsonRecord = Record<string, unknown>;
type JsonPath = Array<string | number>;

const FIELD_LABELS: Record<string, string> = {
  document_type: "Typ dokladu",
  issue_date: "Datum vystaveni",
  taxable_supply_date: "Datum zdanitelneho plneni",
  due_date: "Datum splatnosti",
  invoice_number: "Cislo faktury",
  delivery_note_number: "Dodaci list",
  merchant: "Dodavatel",
  buyer: "Odberatel",
  payment: "Platba",
  order: "Objednavka",
  items: "Polozky",
  tax_summary: "Rekapitulace DPH",
  summary: "Popisek",
  confidence: "Jistota modelu",
  needs_review: "Ke kontrole",
  evidence: "Evidence",
  name: "Nazev",
  user_label: "Moje pojmenovani",
  user_note: "Moje poznamka",
  ico: "ICO",
  dic: "DIC",
  registered_address: "Sidlo",
  store_address: "Provozovna",
  registered_contact: "Kontakt sidla",
  store_contact: "Kontakt provozovny",
  bank_account: "Bankovni ucet",
  billing_address: "Fakturacni adresa",
  delivery_address: "Dodaci adresa",
  order_number: "Cislo objednavky",
  order_date: "Datum objednavky",
  total: "Celkem",
  payment_method: "Zpusob uhrady",
  currency: "Mena",
  variable_symbol: "Variabilni symbol",
  constant_symbol: "Konstantni symbol",
  account_number: "Cislo uctu",
  iban: "IBAN",
  swift: "SWIFT",
  bank_name: "Banka",
  raw: "Puvodni text",
  street: "Ulice",
  city: "Mesto",
  postal_code: "PSC",
  country: "Zeme",
  phone: "Telefon",
  email: "E-mail",
  quantity: "Mnozstvi",
  unit: "Jednotka",
  unit_price: "Cena za jednotku",
  total_price: "Cena celkem",
  tax: "DPH",
  vat_rate: "Sazba DPH",
  vat_amount: "Castka DPH",
  tax_base: "Zaklad dane",
  amount: "Castka"
};

function asRecord(value: unknown): JsonRecord | null {
  return value && typeof value === "object" && !Array.isArray(value) ? (value as JsonRecord) : null;
}

function fieldLabel(key: string | number): string {
  if (typeof key === "number") {
    return `Polozka ${key + 1}`;
  }
  return FIELD_LABELS[key] ?? key.replace(/_/g, " ");
}

function isItemObjectPath(path: JsonPath): boolean {
  return path.length === 2 && path[0] === "items" && typeof path[1] === "number";
}

function structuredEntries(record: JsonRecord, path: JsonPath): Array<[string, unknown]> {
  const entries = Object.entries(record);
  if (!isItemObjectPath(path)) {
    return entries;
  }

  const existing = new Set(entries.map(([key]) => key));
  const additions: Array<[string, unknown]> = [];
  if (!existing.has("user_label")) {
    additions.push(["user_label", null]);
  }
  if (!existing.has("user_note")) {
    additions.push(["user_note", null]);
  }
  return [...entries, ...additions];
}

function inputValue(value: unknown): string {
  if (value === null || value === undefined) {
    return "";
  }
  if (typeof value === "object") {
    return JSON.stringify(value);
  }
  return String(value);
}

function hasOverviewValue(value: unknown): boolean {
  if (value === null || value === undefined || value === "") {
    return false;
  }
  if (Array.isArray(value)) {
    return value.some(hasOverviewValue);
  }
  const record = asRecord(value);
  if (record) {
    return Object.values(record).some(hasOverviewValue);
  }
  return true;
}

function parseEditedValue(previousValue: unknown, value: string): unknown {
  if (value.trim() === "") {
    return null;
  }
  if (typeof previousValue === "number") {
    const normalized = Number(value.replace(",", ".").replace(/\s/g, ""));
    return Number.isNaN(normalized) ? value : normalized;
  }
  if (typeof previousValue === "boolean") {
    return ["true", "1", "ano", "yes"].includes(value.trim().toLowerCase());
  }
  return value;
}

function updateNestedValue(source: unknown, path: JsonPath, value: unknown): unknown {
  if (!path.length) {
    return value;
  }
  const [head, ...tail] = path;
  if (Array.isArray(source)) {
    const next = [...source];
    next[Number(head)] = updateNestedValue(next[Number(head)], tail, value);
    return next;
  }
  const record = asRecord(source) ?? {};
  return {
    ...record,
    [head]: updateNestedValue(record[head], tail, value)
  };
}

function nestedString(source: JsonRecord | undefined, path: string[]): string | null {
  let current: unknown = source;
  for (const key of path) {
    const record = asRecord(current);
    if (!record) {
      return null;
    }
    current = record[key];
  }
  return typeof current === "string" && current.trim() ? current : null;
}

function formatDateLabel(value: string | null | undefined): string {
  if (!value) {
    return "";
  }
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) {
    return value;
  }
  return new Intl.DateTimeFormat("cs-CZ").format(date);
}

function documentIssueDate(extraction: DocumentExtraction | null | undefined): string | null {
  return nestedString(extraction?.structured_json, ["issue_date"]) ?? nestedString(extraction?.structured_json, ["date"]);
}

function documentTitle(document: DocumentItem, extraction: DocumentExtraction | null | undefined): string {
  return extraction?.summary?.trim() || document.filename;
}

function documentCatalogStatus(document: DocumentItem, extraction: DocumentExtraction | null | undefined): string {
  if (extraction) {
    return extraction.review_status === "approved" ? "cataloged" : "uncataloged";
  }
  return document.status;
}

export function App() {
  const [user, setUser] = useState<User | null>(null);
  const [authMode, setAuthMode] = useState<AuthMode>("login");
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [isBusy, setIsBusy] = useState(false);
  const [voiceState, setVoiceState] = useState<VoiceState>("idle");
  const [conversations, setConversations] = useState<Conversation[]>([]);
  const [activeConversation, setActiveConversation] = useState<ConversationDetail | null>(null);
  const [models, setModels] = useState<OllamaModel[]>([]);
  const [selectedModel, setSelectedModel] = useState("");
  const [userSettings, setUserSettings] = useState<UserSettings | null>(null);
  const [ocrProcessingModel, setOcrProcessingModel] = useState("");
  const [ragSourceStrategy, setRagSourceStrategy] = useState<"best_band" | "top_n">("best_band");
  const [ragBestBand, setRagBestBand] = useState("0.08");
  const [ragTopN, setRagTopN] = useState("2");
  const [messageInput, setMessageInput] = useState("");
  const [isSending, setIsSending] = useState(false);
  const [isLoadingChat, setIsLoadingChat] = useState(false);
  const [documents, setDocuments] = useState<DocumentItem[]>([]);
  const [documentFiles, setDocumentFiles] = useState<DocumentFile[]>([]);
  const [documentExtractions, setDocumentExtractions] = useState<Record<string, DocumentExtraction>>({});
  const [activeDocumentId, setActiveDocumentId] = useState<string | null>(null);
  const [activeOcrResult, setActiveOcrResult] = useState<OcrResult | null>(null);
  const [activeExtraction, setActiveExtraction] = useState<DocumentExtraction | null>(null);
  const [activeView, setActiveView] = useState<AppView>("chat");
  const [isUploadingDocument, setIsUploadingDocument] = useState(false);
  const [isAddingDocumentFile, setIsAddingDocumentFile] = useState(false);
  const [isDeletingDocument, setIsDeletingDocument] = useState(false);
  const [isRunningOcr, setIsRunningOcr] = useState(false);
  const [isRunningExtraction, setIsRunningExtraction] = useState(false);
  const [isSavingStructured, setIsSavingStructured] = useState(false);
  const [isSavingSettings, setIsSavingSettings] = useState(false);
  const [documentTextView, setDocumentTextView] = useState<DocumentTextView>("overview");
  const [structuredDraft, setStructuredDraft] = useState<unknown | null>(null);
  const messagesRef = useRef<HTMLDivElement | null>(null);

  const activeDocument = useMemo(
    () => documents.find((document) => document.id === activeDocumentId) ?? documents[0] ?? null,
    [activeDocumentId, documents]
  );
  const activeDocumentTitle = activeDocument ? documentTitle(activeDocument, activeExtraction) : "";
  const activeDocumentDate = formatDateLabel(documentIssueDate(activeExtraction) ?? activeDocument?.created_at);
  const structuredDocument = structuredDraft ?? activeExtraction?.structured_json ?? null;
  const isStructuredDirty =
    activeExtraction !== null &&
    structuredDocument !== null &&
    JSON.stringify(structuredDocument) !== JSON.stringify(activeExtraction.structured_json);
  const isProcessingDocument = isRunningOcr || isRunningExtraction;
  const processButtonLabel = isRunningOcr
    ? documentTextView === "ocr"
      ? "Zpracovavam OCR"
      : "Pripravuji OCR"
    : isRunningExtraction
      ? "Strukturuji"
      : "Process";
  const documentTextPanel = useMemo(() => {
    if (documentTextView === "overview") {
      return {
        title: "Overview",
        content: ""
      };
    }
    if (documentTextView === "structured") {
      return {
        title: "Structured",
        content: activeExtraction?.summary || "Zatim bez strukturovaneho popisku."
      };
    }
    if (documentTextView === "raw") {
      return {
        title: "Structured raw",
        content: structuredDocument ? JSON.stringify(structuredDocument, null, 2) : "Zatim bez strukturovaneho JSON vystupu."
      };
    }
    return {
      title: "OCR",
      content: activeOcrResult?.normalized_text || "Zatim bez extrahovaneho textu."
    };
  }, [activeExtraction, activeOcrResult, documentTextView, structuredDocument]);

  const voiceLabel = useMemo(() => {
    const labels: Record<VoiceState, string> = {
      idle: "SpeechCloud pripraven",
      listening: "Posloucham",
      recognizing: "Rozpoznavam",
      thinking: "Model premysli",
      speaking: "Prehravam odpoved",
      error: "Hlasova chyba"
    };
    return labels[voiceState];
  }, [voiceState]);

  useEffect(() => {
    getMe()
      .then((me) => setUser(me))
      .catch(() => setUser(null));
  }, []);

  useEffect(() => {
    if (!user) {
      setConversations([]);
      setActiveConversation(null);
      setModels([]);
      setSelectedModel("");
      setUserSettings(null);
      setOcrProcessingModel("");
      setDocuments([]);
      setDocumentExtractions({});
      setDocumentFiles([]);
      return;
    }

    setIsLoadingChat(true);
    setError(null);
    Promise.allSettled([listConversations(), listModels(), listDocuments(), getUserSettings()])
      .then(async ([conversationResult, modelResult, documentsResult, settingsResult]) => {
        if (conversationResult.status === "fulfilled") {
          setConversations(conversationResult.value);
          if (conversationResult.value[0]) {
            setActiveConversation(await getConversation(conversationResult.value[0].id));
          }
        }

        if (modelResult.status === "fulfilled") {
          setModels(modelResult.value);
          const defaultModel = modelResult.value.find((model) => model.selected) ?? modelResult.value[0];
          setSelectedModel(defaultModel?.name ?? "");
        } else {
          setError("Nepodarilo se nacist seznam Ollama modelu.");
        }

        if (documentsResult.status === "fulfilled") {
          setDocuments(documentsResult.value);
          setDocumentExtractions({});
          setActiveDocumentId((current) => current ?? documentsResult.value[0]?.id ?? null);
        }

        if (settingsResult.status === "fulfilled") {
          setUserSettings(settingsResult.value);
          setOcrProcessingModel(settingsResult.value.ocr_processing_model ?? "");
          setRagSourceStrategy(settingsResult.value.rag_source_strategy);
          setRagBestBand(String(settingsResult.value.rag_best_band));
          setRagTopN(String(settingsResult.value.rag_top_n));
        }
      })
      .catch((err) => setError(err instanceof Error ? err.message : "Nacteni chatu selhalo"))
      .finally(() => setIsLoadingChat(false));
  }, [user]);

  useEffect(() => {
    const messages = messagesRef.current;
    if (messages) {
      messages.scrollTop = messages.scrollHeight;
    }
  }, [activeConversation?.id, activeConversation?.messages.length, isLoadingChat]);

  useEffect(() => {
    if (activeView !== "documents" || !activeDocument) {
      setActiveOcrResult(null);
      setActiveExtraction(null);
      setStructuredDraft(null);
      setDocumentFiles([]);
      return;
    }

    listDocumentFiles(activeDocument.id)
      .then((files) => {
        setDocumentFiles(files);
        return getDocumentOcr(activeDocument.id);
      })
      .then((result) => {
        setActiveOcrResult(result);
        return getDocumentExtraction(activeDocument.id).catch(() => null);
      })
      .then((extraction) => {
        setActiveExtraction(extraction);
        if (extraction) {
          setDocumentExtractions((current) => ({ ...current, [extraction.document_id]: extraction }));
        }
      })
      .catch(() => {
        setActiveOcrResult(null);
        setActiveExtraction(null);
        setStructuredDraft(null);
      });
  }, [activeDocument?.id, activeView]);

  useEffect(() => {
    setStructuredDraft(activeExtraction?.structured_json ?? null);
  }, [activeExtraction?.id, activeExtraction?.updated_at]);

  useEffect(() => {
    if (!user || activeView !== "documents" || !documents.length) {
      return;
    }

    let cancelled = false;
    Promise.all(
      documents.map((document) =>
        getDocumentExtraction(document.id)
          .then((extraction) => [document.id, extraction] as const)
          .catch(() => null)
      )
    ).then((results) => {
      if (cancelled) {
        return;
      }
      const nextExtractions: Record<string, DocumentExtraction> = {};
      for (const result of results) {
        if (result) {
          nextExtractions[result[0]] = result[1];
        }
      }
      setDocumentExtractions(nextExtractions);
    });

    return () => {
      cancelled = true;
    };
  }, [activeView, documents, user]);

  async function handleAuth(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setError(null);
    setIsBusy(true);
    try {
      if (authMode === "register") {
        await register(email, password);
      }
      await login(email, password);
      setUser(await getMe());
    } catch (err) {
      setError(err instanceof Error ? err.message : "Prihlaseni selhalo");
    } finally {
      setIsBusy(false);
    }
  }

  async function handleLogout() {
    await logout();
    setUser(null);
  }

  async function handleSelectConversation(conversation: Conversation) {
    setError(null);
    setActiveView("chat");
    setIsLoadingChat(true);
    try {
      setActiveConversation(await getConversation(conversation.id));
    } catch (err) {
      setError(err instanceof Error ? err.message : "Nacteni konverzace selhalo");
    } finally {
      setIsLoadingChat(false);
    }
  }

  async function handleNewChat() {
    setActiveView("chat");
    setActiveConversation(null);
    setMessageInput("");
    setError(null);
  }

  async function handleDeleteChat() {
    if (!activeConversation) {
      return;
    }

    const shouldDelete = window.confirm("Smazat tento chat vcetne vsech zprav?");
    if (!shouldDelete) {
      return;
    }

    setError(null);
    setIsLoadingChat(true);
    try {
      await deleteConversation(activeConversation.id);
      const remaining = conversations.filter((conversation) => conversation.id !== activeConversation.id);
      setConversations(remaining);
      setActiveConversation(remaining[0] ? await getConversation(remaining[0].id) : null);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Smazani konverzace selhalo");
    } finally {
      setIsLoadingChat(false);
    }
  }

  async function handleDocumentUpload(event: ChangeEvent<HTMLInputElement>) {
    const file = event.target.files?.[0];
    event.target.value = "";
    if (!file) {
      return;
    }

    setError(null);
    setIsUploadingDocument(true);
    try {
      const document = await uploadDocument(file);
      setActiveView("documents");
      setActiveDocumentId(document.id);
      setDocuments((current) => [document, ...current.filter((item) => item.id !== document.id)]);
      setDocumentExtractions((current) => {
        const next = { ...current };
        delete next[document.id];
        return next;
      });
    } catch (err) {
      setError(err instanceof Error ? err.message : "Nahrani dokumentu selhalo");
    } finally {
      setIsUploadingDocument(false);
    }
  }

  async function handleAddDocumentFile(event: ChangeEvent<HTMLInputElement>) {
    const file = event.target.files?.[0];
    event.target.value = "";
    if (!file || !activeDocument) {
      return;
    }

    setError(null);
    setIsAddingDocumentFile(true);
    try {
      await addDocumentFile(activeDocument.id, file);
      setDocumentFiles(await listDocumentFiles(activeDocument.id));
      setActiveOcrResult(null);
      setActiveExtraction(null);
      setStructuredDraft(null);
      setDocumentExtractions((current) => {
        const next = { ...current };
        delete next[activeDocument.id];
        return next;
      });
      setDocuments(await listDocuments());
    } catch (err) {
      setError(err instanceof Error ? err.message : "Pridani fotky selhalo");
    } finally {
      setIsAddingDocumentFile(false);
    }
  }

  async function handleDeleteDocumentFile(fileId: string) {
    if (!activeDocument || !window.confirm("Smazat tuto fotku z dokladu?")) {
      return;
    }

    setError(null);
    try {
      await deleteDocumentFile(activeDocument.id, fileId);
      setDocumentFiles(await listDocumentFiles(activeDocument.id));
      setActiveOcrResult(null);
      setActiveExtraction(null);
      setStructuredDraft(null);
      setDocumentExtractions((current) => {
        const next = { ...current };
        delete next[activeDocument.id];
        return next;
      });
      setDocuments(await listDocuments());
    } catch (err) {
      setError(err instanceof Error ? err.message : "Smazani fotky selhalo");
    }
  }

  async function handleDeleteDocument() {
    if (!activeDocument || !window.confirm("Smazat cely doklad vcetne vsech fotek a OCR vysledku?")) {
      return;
    }

    setError(null);
    setIsDeletingDocument(true);
    try {
      await deleteDocument(activeDocument.id);
      const refreshedDocuments = await listDocuments();
      setDocuments(refreshedDocuments);
      setActiveDocumentId(refreshedDocuments[0]?.id ?? null);
      setDocumentFiles([]);
      setActiveOcrResult(null);
      setActiveExtraction(null);
      setStructuredDraft(null);
      setDocumentExtractions((current) => {
        const next = { ...current };
        delete next[activeDocument.id];
        return next;
      });
    } catch (err) {
      setError(err instanceof Error ? err.message : "Smazani dokladu selhalo");
    } finally {
      setIsDeletingDocument(false);
    }
  }

  async function refreshProcessedDocument(documentId: string) {
    const [refreshedDocuments, ocrResult, extraction] = await Promise.all([
      listDocuments(),
      getDocumentOcr(documentId).catch(() => null),
      getDocumentExtraction(documentId).catch(() => null)
    ]);
    setDocuments(refreshedDocuments);
    setActiveOcrResult(ocrResult);
    setActiveExtraction(extraction);
    setDocumentExtractions((current) => {
      const next = { ...current };
      if (extraction) {
        next[documentId] = extraction;
      } else {
        delete next[documentId];
      }
      return next;
    });
  }

  async function handleProcessDocument() {
    if (!activeDocument) {
      return;
    }

    const documentId = activeDocument.id;
    setError(null);
    try {
      if (documentTextView === "ocr") {
        setIsRunningOcr(true);
        const ocrJob = await runDocumentOcr(documentId);
        if (ocrJob.status === "failed") {
          throw new Error(ocrJob.error_message ?? "OCR zpracovani selhalo");
        }
        await refreshProcessedDocument(documentId);
        return;
      }

      if (!activeOcrResult) {
        setIsRunningOcr(true);
        const ocrJob = await runDocumentOcr(documentId);
        if (ocrJob.status === "failed") {
          throw new Error(ocrJob.error_message ?? "OCR zpracovani selhalo");
        }
        setIsRunningOcr(false);
      }

      setIsRunningExtraction(true);
      const extractionJob = await runDocumentExtraction(documentId);
      if (extractionJob.status === "failed") {
        throw new Error(extractionJob.error_message ?? "Strukturovani dokladu selhalo");
      }
      await refreshProcessedDocument(documentId);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Zpracovani dokladu selhalo");
    } finally {
      setIsRunningOcr(false);
      setIsRunningExtraction(false);
    }
  }

  async function handleSaveStructuredDocument() {
    if (!activeDocument || !activeExtraction || !structuredDocument || typeof structuredDocument !== "object") {
      return;
    }

    setError(null);
    setIsSavingStructured(true);
    try {
      const saved = await updateDocumentExtraction(activeDocument.id, structuredDocument as Record<string, unknown>);
      setActiveExtraction(saved);
      setStructuredDraft(saved.structured_json);
      setDocumentExtractions((current) => ({ ...current, [saved.document_id]: saved }));
      try {
        const refreshedOcr = await getDocumentOcr(activeDocument.id);
        setActiveOcrResult(refreshedOcr);
      } catch {
        // OCR may be unavailable only for inconsistent historical data; the saved extraction is still authoritative.
      }
    } catch (err) {
      setError(err instanceof Error ? err.message : "Ulozeni struktury dokladu selhalo");
    } finally {
      setIsSavingStructured(false);
    }
  }

  async function handleSaveSettings(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setError(null);
    setIsSavingSettings(true);
    try {
      const saved = await updateUserSettings({
        ocr_processing_model: ocrProcessingModel.trim() || null,
        rag_source_strategy: ragSourceStrategy,
        rag_best_band: Number(ragBestBand),
        rag_top_n: Number(ragTopN)
      });
      setUserSettings(saved);
      setOcrProcessingModel(saved.ocr_processing_model ?? "");
      setRagSourceStrategy(saved.rag_source_strategy);
      setRagBestBand(String(saved.rag_best_band));
      setRagTopN(String(saved.rag_top_n));
    } catch (err) {
      setError(err instanceof Error ? err.message : "Ulozeni nastaveni selhalo");
    } finally {
      setIsSavingSettings(false);
    }
  }

  async function handleSend(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const content = messageInput.trim();
    if (!content) {
      return;
    }

    setError(null);
    setIsSending(true);
    setVoiceState("thinking");
    try {
      let conversation = activeConversation;
      if (!conversation) {
        conversation = await createConversation(content.slice(0, 80));
      }

      const response = await sendMessage(conversation.id, content, selectedModel || undefined);
      setActiveConversation(response.conversation);
      setConversations((current) => {
        const rest = current.filter((item) => item.id !== response.conversation.id);
        return [response.conversation, ...rest];
      });
      setMessageInput("");
    } catch (err) {
      setError(err instanceof Error ? err.message : "Odeslani zpravy selhalo");
      setVoiceState("error");
      return;
    } finally {
      setIsSending(false);
    }
    setVoiceState("idle");
  }

  function handleOpenDocumentSource(documentId: string) {
    setError(null);
    setActiveDocumentId(documentId);
    setActiveView("documents");
  }

  function updateStructuredField(path: JsonPath, previousValue: unknown, value: string) {
    setStructuredDraft((current: unknown | null) => updateNestedValue(current ?? {}, path, parseEditedValue(previousValue, value)));
  }

  function renderStructuredEditor(value: unknown, path: JsonPath = [], depth = 0) {
    if (!activeExtraction) {
      return <p className="structured-empty">Zatim bez strukturovanych dat.</p>;
    }

    if (Array.isArray(value)) {
      return (
        <div className="structured-array">
          {value.length ? (
            value.map((item, index) => (
              <section className="structured-section" style={{ marginLeft: `${Math.min(depth, 4) * 0.7}rem` }} key={index}>
                <h4>{fieldLabel(index)}</h4>
                {renderStructuredEditor(item, [...path, index], depth + 1)}
              </section>
            ))
          ) : (
            <p className="structured-empty">Bez polozek.</p>
          )}
        </div>
      );
    }

    const record = asRecord(value);
    if (record) {
      return (
        <div className="structured-object">
          {structuredEntries(record, path).map(([key, child]) => {
            const childRecord = asRecord(child);
            const childIsComplex = childRecord || Array.isArray(child);
            if (childIsComplex) {
              return (
                <section
                  className="structured-section"
                  style={{ marginLeft: `${Math.min(depth, 4) * 0.7}rem` }}
                  key={key}
                >
                  <h4>{fieldLabel(key)}</h4>
                  {renderStructuredEditor(child, [...path, key], depth + 1)}
                </section>
              );
            }

            const fieldId = `field-${[...path, key].join("-")}`;
            const valueText = inputValue(child);
            const multiline = valueText.length > 80 || key === "summary" || key === "raw";
            return (
              <label className="structured-field" style={{ marginLeft: `${Math.min(depth, 4) * 0.7}rem` }} key={key} htmlFor={fieldId}>
                <span>{fieldLabel(key)}</span>
                {multiline ? (
                  <textarea
                    id={fieldId}
                    value={valueText}
                    placeholder="null"
                    rows={Math.min(5, Math.max(2, Math.ceil(valueText.length / 56)))}
                    onChange={(event) => updateStructuredField([...path, key], child, event.target.value)}
                  />
                ) : (
                  <input
                    id={fieldId}
                    value={valueText}
                    placeholder="null"
                    onChange={(event) => updateStructuredField([...path, key], child, event.target.value)}
                  />
                )}
              </label>
            );
          })}
        </div>
      );
    }

    return <p className="structured-empty">Nepodporovana hodnota.</p>;
  }

  function renderOverview(value: unknown, path: JsonPath = [], depth = 0) {
    if (!activeExtraction || !hasOverviewValue(value)) {
      return <p className="structured-empty">Zatim bez vyplnenych strukturovanych dat.</p>;
    }

    if (Array.isArray(value)) {
      const visibleItems = value
        .map((item, index) => ({ item, index }))
        .filter(({ item }) => hasOverviewValue(item));
      return (
        <div className="overview-array">
          {visibleItems.map(({ item, index }) => (
            <section className="overview-section" style={{ marginLeft: `${Math.min(depth, 4) * 0.7}rem` }} key={index}>
              <h4>{fieldLabel(index)}</h4>
              {renderOverview(item, [...path, index], depth + 1)}
            </section>
          ))}
        </div>
      );
    }

    const record = asRecord(value);
    if (record) {
      const entries = Object.entries(record).filter(([, child]) => hasOverviewValue(child));
      return (
        <div className="overview-object">
          {entries.map(([key, child]) => {
            const childIsComplex = asRecord(child) || Array.isArray(child);
            if (childIsComplex) {
              return (
                <section className="overview-section" style={{ marginLeft: `${Math.min(depth, 4) * 0.7}rem` }} key={key}>
                  <h4>{fieldLabel(key)}</h4>
                  {renderOverview(child, [...path, key], depth + 1)}
                </section>
              );
            }
            return (
              <div className="overview-field" style={{ marginLeft: `${Math.min(depth, 4) * 0.7}rem` }} key={key}>
                <span>{fieldLabel(key)}</span>
                <strong>{inputValue(child)}</strong>
              </div>
            );
          })}
        </div>
      );
    }

    return <p className="structured-empty">{inputValue(value)}</p>;
  }

  if (!user) {
    return (
      <main className="app-shell auth-shell">
        <section className="auth-panel">
          <p className="eyebrow">SP2 Assistant</p>
          <h1>Hlasovy chat nad doklady</h1>
          <p className="muted">
            Prihlaseni je pres secure HTTP-only cookie. Textovy chat se pripojuje na nakonfigurovany Ollama server.
          </p>
          <form className="auth-form" onSubmit={handleAuth}>
            <label>
              Email
              <input value={email} onChange={(event) => setEmail(event.target.value)} type="email" required />
            </label>
            <label>
              Heslo
              <input
                value={password}
                onChange={(event) => setPassword(event.target.value)}
                type="password"
                minLength={8}
                required
              />
            </label>
            {error && <p className="error-text">{error}</p>}
            <button type="submit" disabled={isBusy}>
              {authMode === "login" ? "Prihlasit" : "Registrovat a prihlasit"}
            </button>
          </form>
          <button className="ghost-button" onClick={() => setAuthMode(authMode === "login" ? "register" : "login")}>
            {authMode === "login" ? "Vytvorit ucet" : "Mam ucet"}
          </button>
        </section>
      </main>
    );
  }

  return (
    <main className="app-shell">
      <aside className="sidebar panel">
        <div>
          <p className="eyebrow">SP2 Assistant</p>
          <h2>Chat shell</h2>
        </div>
        <button className="primary-button" onClick={handleNewChat}>
          <Plus size={18} />
          Novy chat
        </button>
        <nav className="main-nav" aria-label="Hlavni navigace">
          <button className={activeView === "chat" ? "active" : ""} onClick={() => setActiveView("chat")} type="button">
            <MessageSquare size={18} />
            Chat
          </button>
          <button
            className={activeView === "documents" ? "active" : ""}
            onClick={() => setActiveView("documents")}
            type="button"
          >
            <FileText size={18} />
            Doklady
          </button>
        </nav>
        <div className="status-stack">
          <div className="status-card">
            <Sparkles size={18} />
            <div>
              <strong>Login hotovy</strong>
              <span>{user.email}</span>
            </div>
          </div>
          <div className="status-card muted-card">
            <FileText size={18} />
            <div>
              <strong>Doklady</strong>
              <span>{documents.length ? `${documents.length} nahrano` : "Zatim bez dokladu"}</span>
            </div>
          </div>
        </div>
        {activeView === "chat" && (
          <div className="conversation-list" aria-label="Seznam konverzaci">
            {conversations.map((conversation) => (
              <button
                key={conversation.id}
                className={`conversation ${activeConversation?.id === conversation.id ? "active" : ""}`}
                onClick={() => handleSelectConversation(conversation)}
                type="button"
              >
                {conversation.title}
              </button>
            ))}
          </div>
        )}
        <button className="ghost-button" onClick={() => setActiveView("settings")} type="button">
          <SettingsIcon size={18} />
          Nastaveni
        </button>
        <button className="ghost-button" onClick={handleLogout}>
          <LogOut size={18} />
          Odhlasit
        </button>
      </aside>

      {activeView === "chat" ? (
      <section className="workspace-panel chat-panel panel">
        <header className="chat-header">
          <div>
            <p className="eyebrow">Ollama + SpeechCloud</p>
            <h1>Chat s doklady</h1>
          </div>
          <div className="header-actions">
            <label className="model-select">
              <Bot size={18} />
              <select
                value={selectedModel}
                onChange={(event) => setSelectedModel(event.target.value)}
                disabled={!models.length || isSending}
                aria-label="Ollama model"
              >
                {models.length ? (
                  models.map((model) => (
                    <option key={model.name} value={model.name}>
                      {model.name}
                    </option>
                  ))
                ) : (
                  <option value="">Vychozi model</option>
                )}
              </select>
            </label>
            <div className={`voice-pill ${voiceState}`}>
              <Mic size={18} />
              {voiceLabel}
            </div>
            {activeConversation && (
              <button
                className="danger-button icon-button"
                onClick={handleDeleteChat}
                type="button"
                disabled={isSending || isLoadingChat}
                aria-label="Smazat chat"
                title="Smazat chat"
              >
                <Trash2 size={18} />
              </button>
            )}
          </div>
        </header>

        <div className="messages" ref={messagesRef}>
          {isLoadingChat ? (
            <div className="empty-state">
              <Sparkles size={26} />
              <h2>Nacitam chat</h2>
            </div>
          ) : activeConversation?.messages.length ? (
            activeConversation.messages.map((message) => (
              <article key={message.id} className={`message ${message.role}`}>
                <span>{message.role === "user" ? "Vy" : message.model ?? "Assistant"}</span>
                <p>{message.content}</p>
                {message.role === "assistant" && message.retrieval ? (
                  <div className="message-retrieval" aria-label="Pouzite vyhledavani">
                    {message.retrieval.used_rag && <b>used rag</b>}
                    {message.retrieval.used_search && <b>used search</b>}
                    {!message.retrieval.used_rag && !message.retrieval.used_search && <b>direct answer</b>}
                    <b>{message.retrieval.source_count} sources</b>
                  </div>
                ) : null}
                {message.role === "assistant" && message.sources?.length ? (
                  <div className="message-sources" aria-label="Zdroje odpovedi">
                    <b>Zdroje</b>
                    {message.sources.map((source) => (
                      <button
                        key={source.document_id}
                        type="button"
                        onClick={() => handleOpenDocumentSource(source.document_id)}
                        title={source.filename ?? source.title}
                      >
                        <FileText size={15} />
                        <span>{source.title}</span>
                      </button>
                    ))}
                  </div>
                ) : null}
              </article>
            ))
          ) : (
            <div className="empty-state">
              <Sparkles size={26} />
              <h2>Poslete prvni zpravu.</h2>
              <p>Odpoved prijde z externi Ollamy a podle potreby pouzije vyhledavani v dokladech.</p>
            </div>
          )}
        </div>

        {error && <p className="error-text">{error}</p>}
        <form className="composer" aria-label="Chat composer" onSubmit={handleSend}>
          <input
            value={messageInput}
            onChange={(event) => setMessageInput(event.target.value)}
            placeholder="Zeptejte se na cokoliv..."
            disabled={isSending}
          />
          <button type="submit" disabled={isSending || !messageInput.trim()}>
            <Send size={18} />
            {isSending ? "Odesilam" : "Odeslat"}
          </button>
        </form>
      </section>
      ) : activeView === "documents" ? (
        <section className="workspace-panel documents-page panel">
          <header className="documents-header">
            <div>
              <p className="eyebrow">OCR pipeline</p>
              <h1>Doklady</h1>
            </div>
            <div className="upload-actions page-upload-actions">
              <label className={`upload-drop ${isUploadingDocument ? "is-loading" : ""}`}>
                <UploadCloud size={20} />
                <span>{isUploadingDocument ? "Nahravam..." : "Nahrat soubor"}</span>
                <input
                  className="file-input"
                  type="file"
                  accept="image/png,image/jpeg,application/pdf"
                  onChange={handleDocumentUpload}
                  disabled={isUploadingDocument}
                />
              </label>
              <label className={`upload-drop ${isUploadingDocument ? "is-loading" : ""}`}>
                <Camera size={20} />
                <span>Vyfotit doklad</span>
                <input
                  className="file-input"
                  type="file"
                  accept="image/png,image/jpeg"
                  capture="environment"
                  onChange={handleDocumentUpload}
                  disabled={isUploadingDocument}
                />
              </label>
            </div>
          </header>

          <div className="documents-workspace">
            <div className="documents-list-panel">
              <div className="documents-list-head">
                <span>Doklad</span>
                <span>Datum</span>
                <span>Stav</span>
              </div>
              <div className="documents-table" aria-label="Seznam dokumentu">
                {documents.length ? (
                  documents.map((document) => {
                    const extraction = documentExtractions[document.id];
                    const dateLabel = formatDateLabel(documentIssueDate(extraction) ?? document.created_at);
                    return (
                      <button
                        className={`document-row ${activeDocument?.id === document.id ? "active" : ""}`}
                        key={document.id}
                        onClick={() => setActiveDocumentId(document.id)}
                        type="button"
                      >
                        <span className="document-row-title">
                          <FileText size={16} />
                          <span>
                            <strong>{documentTitle(document, extraction)}</strong>
                            <small>{document.filename}</small>
                          </span>
                        </span>
                        <time dateTime={documentIssueDate(extraction) ?? document.created_at}>{dateLabel}</time>
                        <b>{documentCatalogStatus(document, extraction)}</b>
                      </button>
                    );
                  })
                ) : (
                  <div className="empty-state documents-empty">
                    <FileText size={26} />
                    <h2>Zatim zadne doklady.</h2>
                    <p>Nahrajte PDF, obrazek, nebo vyfotte uctenku telefonem.</p>
                  </div>
                )}
              </div>
            </div>

            <aside className="document-detail">
              {activeDocument ? (
                <>
                  <header className="document-detail-header">
                    <div>
                      <p className="eyebrow">Doklad</p>
                      <h2>{activeDocumentTitle}</h2>
                      <span>{activeDocumentDate || activeDocument.filename}</span>
                    </div>
                    <strong>{documentCatalogStatus(activeDocument, activeExtraction)}</strong>
                  </header>
                  <div className="document-preview">
                    <div className="document-preview-head">
                      <FileText size={32} />
                      <div>
                        <strong>Soubory dokladu</strong>
                        <span>{documentFiles.length ? `${documentFiles.length} casti` : "Zatim bez nactenych casti"}</span>
                      </div>
                    </div>
                    <div className="document-file-list">
                      {documentFiles.length ? (
                        documentFiles.map((file) => (
                          <div className="document-file-row" key={file.id}>
                            <span>
                              <FileText size={16} />
                              {file.sort_order + 1}. {file.filename}
                            </span>
                            <button
                              className="danger-button icon-button"
                              onClick={() => handleDeleteDocumentFile(file.id)}
                              type="button"
                              disabled={documentFiles.length <= 1}
                              aria-label="Smazat fotku"
                              title={documentFiles.length <= 1 ? "Posledni fotku smaze smazani celeho dokladu" : "Smazat fotku"}
                            >
                              <Trash2 size={16} />
                            </button>
                          </div>
                        ))
                      ) : (
                        <span>Nahled bude aktivni po doplneni bezpecneho download endpointu.</span>
                      )}
                    </div>
                  </div>
                  <div className="document-actions">
                    <label className={`upload-drop compact-upload ${isAddingDocumentFile ? "is-loading" : ""}`}>
                      <UploadCloud size={18} />
                      <span>{isAddingDocumentFile ? "Pridavam" : "Pridat fotku/PDF"}</span>
                      <input
                        className="file-input"
                        type="file"
                        accept="image/png,image/jpeg,application/pdf"
                        onChange={handleAddDocumentFile}
                        disabled={isAddingDocumentFile || isDeletingDocument}
                      />
                    </label>
                    <label className={`upload-drop compact-upload ${isAddingDocumentFile ? "is-loading" : ""}`}>
                      <Camera size={18} />
                      <span>Vyfotit cast</span>
                      <input
                        className="file-input"
                        type="file"
                        accept="image/png,image/jpeg"
                        capture="environment"
                        onChange={handleAddDocumentFile}
                        disabled={isAddingDocumentFile || isDeletingDocument}
                      />
                    </label>
                    <button
                      className="primary-button"
                      onClick={handleProcessDocument}
                      type="button"
                      disabled={isProcessingDocument || isUploadingDocument || isAddingDocumentFile || isDeletingDocument}
                    >
                      <Sparkles size={18} />
                      {processButtonLabel}
                    </button>
                    <button
                      className="danger-button"
                      onClick={handleDeleteDocument}
                      type="button"
                      disabled={isDeletingDocument}
                    >
                      <Trash2 size={18} />
                      {isDeletingDocument ? "Mazu" : "Smazat doklad"}
                    </button>
                  </div>
                  <div className="document-processing-strip">
                    <div>
                      <span>OCR metadata</span>
                      <strong>
                        {activeOcrResult
                          ? `${activeOcrResult.engine}, ${activeOcrResult.page_count} stran`
                          : "Ceka na OCR"}
                      </strong>
                    </div>
                    <div className="document-view-switch" role="tablist" aria-label="Zobrazeni textu dokladu">
                      <button
                        className={documentTextView === "overview" ? "active" : ""}
                        onClick={() => setDocumentTextView("overview")}
                        role="tab"
                        type="button"
                        aria-selected={documentTextView === "overview"}
                      >
                        Overview
                      </button>
                      <button
                        className={documentTextView === "structured" ? "active" : ""}
                        onClick={() => setDocumentTextView("structured")}
                        role="tab"
                        type="button"
                        aria-selected={documentTextView === "structured"}
                      >
                        Edit
                      </button>
                      <button
                        className={documentTextView === "raw" ? "active" : ""}
                        onClick={() => setDocumentTextView("raw")}
                        role="tab"
                        type="button"
                        aria-selected={documentTextView === "raw"}
                      >
                        Raw
                      </button>
                      <button
                        className={documentTextView === "ocr" ? "active" : ""}
                        onClick={() => setDocumentTextView("ocr")}
                        role="tab"
                        type="button"
                        aria-selected={documentTextView === "ocr"}
                      >
                        OCR
                      </button>
                    </div>
                    {documentTextView === "structured" && (
                      <button
                        className="primary-button structured-save-button"
                        onClick={handleSaveStructuredDocument}
                        type="button"
                        disabled={!isStructuredDirty || isSavingStructured || isProcessingDocument}
                      >
                        <Save size={16} />
                        {isSavingStructured ? "Ukladam" : "Ulozit"}
                      </button>
                    )}
                  </div>
                  <div className="ocr-text-panel">
                    <span>{documentTextPanel.title}</span>
                    {documentTextView === "overview" ? (
                      <div className="overview-panel">{renderOverview(structuredDocument)}</div>
                    ) : documentTextView === "structured" ? (
                      <div className="structured-editor">{renderStructuredEditor(structuredDocument)}</div>
                    ) : (
                      <pre>{documentTextPanel.content}</pre>
                    )}
                  </div>
                </>
              ) : (
                <div className="empty-state documents-empty">
                  <Sparkles size={26} />
                  <h2>Vyberte doklad.</h2>
                  <p>Detail pozdeji ukaze nahled fotografie, OCR text a extrahovana pole.</p>
                </div>
              )}
            </aside>
          </div>

          {error && <p className="error-text">{error}</p>}
        </section>
      ) : (
        <section className="workspace-panel settings-page panel">
          <header className="settings-header">
            <div>
              <p className="eyebrow">Nastaveni</p>
              <h1>Zpracovani dokumentu</h1>
            </div>
          </header>

          <form className="settings-form" onSubmit={handleSaveSettings}>
            <section className="settings-section">
              <div>
                <h2>Zpracovani dokumentu</h2>
                <p>
                  Model pro zpracovani OCR se pouzije pro prevod OCR textu na strukturovany JSON a popisek pro RAG.
                </p>
              </div>
              <label className="settings-field">
                <span>Model pro zpracovani OCR</span>
                <select
                  value={ocrProcessingModel}
                  onChange={(event) => setOcrProcessingModel(event.target.value)}
                  disabled={isSavingSettings}
                >
                  <option value="">Vychozi model serveru</option>
                  {models.map((model) => (
                    <option key={model.name} value={model.name}>
                      {model.name}
                    </option>
                  ))}
                  {ocrProcessingModel && !models.some((model) => model.name === ocrProcessingModel) ? (
                    <option value={ocrProcessingModel}>{ocrProcessingModel}</option>
                  ) : null}
                </select>
              </label>
              <div className="settings-current">
                <span>Aktualne ulozeno</span>
                <strong>{userSettings?.ocr_processing_model ?? "Vychozi model serveru"}</strong>
              </div>
            </section>
            <section className="settings-section">
              <div>
                <h2>RAG zdroje</h2>
                <p>
                  Určuje, kolik nalezených dokladů se zobrazí pod odpovědí jako klikatelné zdroje.
                </p>
              </div>
              <label className="settings-field">
                <span>Strategie zdrojů</span>
                <select
                  value={ragSourceStrategy}
                  onChange={(event) => setRagSourceStrategy(event.target.value as "best_band" | "top_n")}
                  disabled={isSavingSettings}
                >
                  <option value="best_band">Best band</option>
                  <option value="top_n">Top N</option>
                </select>
              </label>
              <div className="settings-grid">
                <label className="settings-field">
                  <span>Best band</span>
                  <input
                    type="number"
                    min="0"
                    max="1"
                    step="0.01"
                    value={ragBestBand}
                    onChange={(event) => setRagBestBand(event.target.value)}
                    disabled={isSavingSettings || ragSourceStrategy !== "best_band"}
                  />
                </label>
                <label className="settings-field">
                  <span>Top N</span>
                  <input
                    type="number"
                    min="1"
                    max="10"
                    step="1"
                    value={ragTopN}
                    onChange={(event) => setRagTopN(event.target.value)}
                    disabled={isSavingSettings}
                  />
                </label>
              </div>
              <div className="settings-current">
                <span>Aktualne ulozeno</span>
                <strong>
                  {userSettings?.rag_source_strategy === "top_n"
                    ? `Top ${userSettings.rag_top_n}`
                    : `Best band ${userSettings?.rag_best_band ?? 0.08}`}
                </strong>
              </div>
            </section>
            {error && <p className="error-text">{error}</p>}
            <button className="primary-button settings-save" type="submit" disabled={isSavingSettings}>
              <SettingsIcon size={18} />
              {isSavingSettings ? "Ukladam" : "Ulozit nastaveni"}
            </button>
          </form>
        </section>
      )}
    </main>
  );
}
