import {
  Bot,
  Camera,
  Download,
  FileText,
  GripVertical,
  LogOut,
  MessageSquare,
  Mic,
  MicOff,
  PhoneCall,
  PhoneOff,
  Plus,
  Save,
  Send,
  Server,
  Settings as SettingsIcon,
  Sparkles,
  Trash2,
  UploadCloud
} from "lucide-react";
import {
  ChangeEvent,
  DragEvent,
  FormEvent,
  PointerEvent as ReactPointerEvent,
  ReactNode,
  useEffect,
  useMemo,
  useRef,
  useState
} from "react";

import {
  ChatSource,
  Conversation,
  ConversationDetail,
  DocumentExtraction,
  DocumentFile,
  DocumentItem,
  InferenceConfiguration,
  InferenceRole,
  InferenceRouting,
  OcrResult,
  OllamaModel,
  User,
  UserSettings,
  addDocumentFile,
  createConversation,
  createVoiceSession,
  deleteConversation,
  deleteDocument,
  deleteDocumentFile,
  documentFileDownloadUrl,
  endVoiceSession,
  getDocumentExtraction,
  getDocumentOcr,
  getInferenceConfiguration,
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
  updateInferenceConfiguration,
  updateUserSettings,
  uploadDocument
} from "./lib/api";

type AuthMode = "login" | "register";
type VoiceState = "idle" | "connecting" | "listening" | "recognizing" | "thinking" | "speaking" | "error" | "ended";
type AppView = "chat" | "documents" | "settings";
type DocumentTextView = "overview" | "structured" | "raw" | "ocr";
type JsonRecord = Record<string, unknown>;
type JsonPath = Array<string | number>;
type DialToneController = {
  context: AudioContext;
  intervalId: number;
};
type VoiceOverlayPosition = { x: number; y: number };
type VoiceOverlayDrag = VoiceOverlayPosition & { pointerId: number };
const INFERENCE_ROLES: Array<{ id: InferenceRole; label: string; description: string }> = [
  { id: "chat", label: "Chat", description: "Rozhodování agenta a odpovědi" },
  { id: "embedding", label: "Embedding", description: "Vektory pro RAG" },
  { id: "reranker", label: "Reranking", description: "Volitelné přeseřazení kandidátů" },
  { id: "ocr", label: "OCR", description: "Rozpoznání textu z obrazu" },
  { id: "structuring", label: "Strukturace", description: "JSON a popisek dokladu" }
];
type SpeechCloudClient = {
  on: (event: string, handler: (payload?: unknown) => void) => void;
  init: () => void;
  dm_send_message: (payload: { data: unknown }) => void;
  tts_stop: () => void;
  terminate: () => void;
};

declare global {
  interface Window {
    SpeechCloud?: new (options: Record<string, unknown>) => SpeechCloudClient;
  }
}

const TTS_VOICES = [
  { value: "Iva210", label: "Iva" },
  { value: "Jan210", label: "Jan" },
  { value: "Jiri210", label: "Jiří" },
  { value: "Katerina210", label: "Kateřina" },
  { value: "Radka210", label: "Radka" },
  { value: "Stanislav210", label: "Stanislav" },
  { value: "Alena210", label: "Alena" }
];

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

function voiceTranscriptFromPayload(value: unknown, depth = 0): string | null {
  if (depth > 3) {
    return null;
  }
  if (typeof value === "string" && value.trim()) {
    return value.trim();
  }
  const record = asRecord(value);
  if (!record) {
    return null;
  }
  for (const key of ["transcript", "word_1best", "utterance", "text"]) {
    const candidate = record[key];
    if (typeof candidate === "string" && candidate.trim()) {
      return candidate.trim();
    }
  }
  return (
    voiceTranscriptFromPayload(record.result, depth + 1) ??
    voiceTranscriptFromPayload(record.data, depth + 1)
  );
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

function renderInlineMarkdown(text: string, keyPrefix: string): ReactNode[] {
  const parts = text.split(/(`[^`]+`|\*\*[^*]+\*\*|\*[^*]+\*)/g);
  return parts.map((part, index) => {
    const key = `${keyPrefix}-${index}`;
    if (part.startsWith("`") && part.endsWith("`")) {
      return <code key={key}>{part.slice(1, -1)}</code>;
    }
    if (part.startsWith("**") && part.endsWith("**")) {
      return <strong key={key}>{part.slice(2, -2)}</strong>;
    }
    if (part.startsWith("*") && part.endsWith("*")) {
      return <em key={key}>{part.slice(1, -1)}</em>;
    }
    return part;
  });
}

function renderMarkdown(content: string): ReactNode {
  const blocks: ReactNode[] = [];
  const paragraph: string[] = [];
  let list: { type: "ul" | "ol"; items: string[] } | null = null;
  let codeBlock: string[] | null = null;

  const flushParagraph = () => {
    if (!paragraph.length) {
      return;
    }
    const text = paragraph.join(" ");
    blocks.push(<p key={`p-${blocks.length}`}>{renderInlineMarkdown(text, `p-${blocks.length}`)}</p>);
    paragraph.length = 0;
  };

  const flushList = () => {
    if (!list) {
      return;
    }
    const Tag = list.type;
    blocks.push(
      <Tag key={`list-${blocks.length}`}>
        {list.items.map((item, index) => (
          <li key={index}>{renderInlineMarkdown(item, `li-${blocks.length}-${index}`)}</li>
        ))}
      </Tag>
    );
    list = null;
  };

  const flushCode = () => {
    if (!codeBlock) {
      return;
    }
    blocks.push(
      <pre key={`code-${blocks.length}`}>
        <code>{codeBlock.join("\n")}</code>
      </pre>
    );
    codeBlock = null;
  };

  content.split(/\r?\n/).forEach((line) => {
    if (line.trim().startsWith("```")) {
      if (codeBlock) {
        flushCode();
      } else {
        flushParagraph();
        flushList();
        codeBlock = [];
      }
      return;
    }

    if (codeBlock) {
      codeBlock.push(line);
      return;
    }

    if (!line.trim()) {
      flushParagraph();
      flushList();
      return;
    }

    const heading = line.match(/^(#{1,3})\s+(.+)$/);
    if (heading) {
      flushParagraph();
      flushList();
      const level = heading[1].length;
      const content = renderInlineMarkdown(heading[2], `h-${blocks.length}`);
      if (level === 1) {
        blocks.push(<h3 key={`h-${blocks.length}`}>{content}</h3>);
      } else if (level === 2) {
        blocks.push(<h4 key={`h-${blocks.length}`}>{content}</h4>);
      } else {
        blocks.push(<h5 key={`h-${blocks.length}`}>{content}</h5>);
      }
      return;
    }

    const bullet = line.match(/^\s*[-*]\s+(.+)$/);
    if (bullet) {
      flushParagraph();
      if (list?.type !== "ul") {
        flushList();
        list = { type: "ul", items: [] };
      }
      list.items.push(bullet[1]);
      return;
    }

    const ordered = line.match(/^\s*\d+[.)]\s+(.+)$/);
    if (ordered) {
      flushParagraph();
      if (list?.type !== "ol") {
        flushList();
        list = { type: "ol", items: [] };
      }
      list.items.push(ordered[1]);
      return;
    }

    flushList();
    paragraph.push(line.trim());
  });

  flushParagraph();
  flushList();
  flushCode();

  return <div className="markdown-message">{blocks.length ? blocks : <p>{content}</p>}</div>;
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

let speechCloudScriptPromise: Promise<void> | null = null;

function loadSpeechCloudScript(): Promise<void> {
  if (window.SpeechCloud) {
    return Promise.resolve();
  }
  if (speechCloudScriptPromise) {
    return speechCloudScriptPromise;
  }
  const scriptUrl =
    import.meta.env.VITE_SPEECHCLOUD_SCRIPT_URL ?? "https://speechcloud.kky.zcu.cz:9444/speechcloud-3.0.js";
  speechCloudScriptPromise = new Promise((resolve, reject) => {
    const script = document.createElement("script");
    script.src = scriptUrl;
    script.async = true;
    script.onload = () => resolve();
    script.onerror = () => reject(new Error("Nepodarilo se nacist SpeechCloud klienta."));
    document.head.appendChild(script);
  });
  return speechCloudScriptPromise;
}

export function App() {
  const [user, setUser] = useState<User | null>(null);
  const [authMode, setAuthMode] = useState<AuthMode>("login");
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [isBusy, setIsBusy] = useState(false);
  const [voiceState, setVoiceState] = useState<VoiceState>("idle");
  const [voiceSessionId, setVoiceSessionId] = useState<string | null>(null);
  const [voiceTranscript, setVoiceTranscript] = useState("");
  const [voiceAnswer, setVoiceAnswer] = useState("");
  const [voiceSources, setVoiceSources] = useState<ChatSource[]>([]);
  const [voiceError, setVoiceError] = useState<string | null>(null);
  const [isVoiceMuted, setIsVoiceMuted] = useState(false);
  const [voiceOverlayPosition, setVoiceOverlayPosition] = useState<VoiceOverlayPosition | null>(null);
  const [conversations, setConversations] = useState<Conversation[]>([]);
  const [activeConversation, setActiveConversation] = useState<ConversationDetail | null>(null);
  const [models, setModels] = useState<OllamaModel[]>([]);
  const [inferenceConfiguration, setInferenceConfiguration] = useState<InferenceConfiguration | null>(null);
  const [inferenceRouting, setInferenceRouting] = useState<InferenceRouting | null>(null);
  const [isSavingInference, setIsSavingInference] = useState(false);
  const [selectedModel, setSelectedModel] = useState("");
  const [userSettings, setUserSettings] = useState<UserSettings | null>(null);
  const [defaultChatModel, setDefaultChatModel] = useState("");
  const [ttsVoice, setTtsVoice] = useState("");
  const [ocrProcessingModel, setOcrProcessingModel] = useState("");
  const [ragSourceStrategy, setRagSourceStrategy] = useState<"best_band" | "top_n">("best_band");
  const [ragBestBand, setRagBestBand] = useState("0.08");
  const [ragRerankerBestBand, setRagRerankerBestBand] = useState("0.10");
  const [ragRerankerMinScore, setRagRerankerMinScore] = useState("0.50");
  const [ragTopN, setRagTopN] = useState("2");
  const [messageInput, setMessageInput] = useState("");
  const [isSending, setIsSending] = useState(false);
  const [isLoadingChat, setIsLoadingChat] = useState(false);
  const [documents, setDocuments] = useState<DocumentItem[]>([]);
  const [documentFiles, setDocumentFiles] = useState<DocumentFile[]>([]);
  const [activeDocumentFileId, setActiveDocumentFileId] = useState<string | null>(null);
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
  const dialToneRef = useRef<DialToneController | null>(null);
  const speechCloudRef = useRef<SpeechCloudClient | null>(null);
  const voiceOverlayRef = useRef<HTMLDivElement | null>(null);
  const voiceOverlayDragRef = useRef<VoiceOverlayDrag | null>(null);

  const activeDocument = useMemo(
    () => documents.find((document) => document.id === activeDocumentId) ?? documents[0] ?? null,
    [activeDocumentId, documents]
  );
  const structuringModels = useMemo(() => {
    if (!inferenceConfiguration || !inferenceRouting) {
      return models.map((model) => model.name);
    }
    return (
      inferenceConfiguration.servers.find((server) => server.id === inferenceRouting.structuring_server_id)?.models ?? []
    );
  }, [inferenceConfiguration, inferenceRouting, models]);
  const activeDocumentTitle = activeDocument ? documentTitle(activeDocument, activeExtraction) : "";
  const activeDocumentDate = formatDateLabel(documentIssueDate(activeExtraction) ?? activeDocument?.created_at);
  const activeDocumentFile =
    documentFiles.find((file) => file.id === activeDocumentFileId) ?? documentFiles[0] ?? null;
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
      connecting: "Pripojuji hovor",
      listening: "Posloucham",
      recognizing: "Rozpoznavam",
      thinking: "Model premysli",
      speaking: "Prehravam odpoved",
      error: "Hlasova chyba",
      ended: "Hovor ukoncen"
    };
    return labels[voiceState];
  }, [voiceState]);

  useEffect(() => {
    getMe()
      .then((me) => setUser(me))
      .catch(() => setUser(null));
  }, []);

  useEffect(() => {
    const keepVoiceOverlayVisible = () => {
      const overlay = voiceOverlayRef.current;
      if (!overlay) {
        return;
      }
      setVoiceOverlayPosition((current) => {
        if (!current) {
          return current;
        }
        const margin = 8;
        return {
          x: Math.min(Math.max(margin, current.x), Math.max(margin, window.innerWidth - overlay.offsetWidth - margin)),
          y: Math.min(Math.max(margin, current.y), Math.max(margin, window.innerHeight - overlay.offsetHeight - margin))
        };
      });
    };
    window.addEventListener("resize", keepVoiceOverlayVisible);
    return () => window.removeEventListener("resize", keepVoiceOverlayVisible);
  }, []);

  useEffect(() => {
    if (!user) {
      setConversations([]);
      setActiveConversation(null);
      setModels([]);
      setInferenceConfiguration(null);
      setInferenceRouting(null);
      setSelectedModel("");
      setUserSettings(null);
      setDefaultChatModel("");
      setTtsVoice("");
      setOcrProcessingModel("");
      setRagRerankerBestBand("0.10");
      setRagRerankerMinScore("0.50");
      setDocuments([]);
      setDocumentExtractions({});
      setDocumentFiles([]);
      return;
    }

    setIsLoadingChat(true);
    setError(null);
    Promise.allSettled([listConversations(), listModels(), listDocuments(), getUserSettings(), getInferenceConfiguration()])
      .then(async ([conversationResult, modelResult, documentsResult, settingsResult, inferenceResult]) => {
        if (conversationResult.status === "fulfilled") {
          setConversations(conversationResult.value);
          if (conversationResult.value[0]) {
            setActiveConversation(await getConversation(conversationResult.value[0].id));
          }
        }

        if (modelResult.status === "fulfilled") {
          setModels(modelResult.value);
          const configuredModel =
            settingsResult.status === "fulfilled" ? settingsResult.value.default_chat_model : null;
          const defaultModel =
            modelResult.value.find((model) => model.name === configuredModel) ??
            modelResult.value.find((model) => model.selected) ??
            modelResult.value[0];
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
          setDefaultChatModel(settingsResult.value.default_chat_model ?? "");
          setTtsVoice(settingsResult.value.tts_voice ?? "");
          setOcrProcessingModel(settingsResult.value.ocr_processing_model ?? "");
          setRagSourceStrategy(settingsResult.value.rag_source_strategy);
          setRagBestBand(String(settingsResult.value.rag_best_band));
          setRagRerankerBestBand(String(settingsResult.value.rag_reranker_best_band));
          setRagRerankerMinScore(String(settingsResult.value.rag_reranker_min_score));
          setRagTopN(String(settingsResult.value.rag_top_n));
        }

        if (inferenceResult.status === "fulfilled") {
          setInferenceConfiguration(inferenceResult.value);
          setInferenceRouting(inferenceResult.value.routing);
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
      setActiveDocumentFileId(null);
      return;
    }

    listDocumentFiles(activeDocument.id)
      .then((files) => {
        setDocumentFiles(files);
        setActiveDocumentFileId((current) =>
          current && files.some((file) => file.id === current) ? current : files[0]?.id ?? null
        );
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

  function promoteConversation(conversation: ConversationDetail) {
    setActiveConversation(conversation);
    setConversations((current) => {
      const rest = current.filter((item) => item.id !== conversation.id);
      return [conversation, ...rest];
    });
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
        default_chat_model: defaultChatModel.trim() || null,
        tts_voice: ttsVoice.trim() || null,
        ocr_processing_model: ocrProcessingModel.trim() || null,
        rag_source_strategy: ragSourceStrategy,
        rag_best_band: Number(ragBestBand),
        rag_reranker_best_band: Number(ragRerankerBestBand),
        rag_reranker_min_score: Number(ragRerankerMinScore),
        rag_top_n: Number(ragTopN)
      });
      setUserSettings(saved);
      setDefaultChatModel(saved.default_chat_model ?? "");
      setTtsVoice(saved.tts_voice ?? "");
      setOcrProcessingModel(saved.ocr_processing_model ?? "");
      setRagSourceStrategy(saved.rag_source_strategy);
      setRagBestBand(String(saved.rag_best_band));
      setRagRerankerBestBand(String(saved.rag_reranker_best_band));
      setRagRerankerMinScore(String(saved.rag_reranker_min_score));
      setRagTopN(String(saved.rag_top_n));
      const effectiveChatModel =
        models.find((model) => model.name === saved.default_chat_model) ??
        models.find((model) => model.selected) ??
        models[0];
      setSelectedModel(effectiveChatModel?.name ?? "");
    } catch (err) {
      setError(err instanceof Error ? err.message : "Ulozeni nastaveni selhalo");
    } finally {
      setIsSavingSettings(false);
    }
  }

  function assignInferenceRole(role: InferenceRole, serverId: string | null) {
    setInferenceRouting((current) => {
      if (!current) {
        return current;
      }
      const next = { ...current, [`${role}_server_id`]: serverId } as InferenceRouting;
      if (role === "embedding" || role === "reranker") {
        const modelField = `${role}_model` as "embedding_model" | "reranker_model";
        const serverModels =
          inferenceConfiguration?.servers.find((server) => server.id === serverId)?.models ?? [];
        if (!serverId || !next[modelField] || !serverModels.includes(next[modelField] as string)) {
          next[modelField] = null;
        }
      }
      return next;
    });
  }

  function handleInferenceDrop(event: DragEvent<HTMLDivElement>, serverId: string) {
    event.preventDefault();
    const role = event.dataTransfer.getData("application/x-sp2-inference-role") as InferenceRole;
    if (INFERENCE_ROLES.some((item) => item.id === role)) {
      assignInferenceRole(role, serverId);
    }
  }

  async function handleSaveInference() {
    if (!inferenceRouting) {
      return;
    }
    setError(null);
    if (!inferenceRouting.embedding_model) {
      setError("Vyberte platný embedding model na přiřazeném serveru.");
      return;
    }
    if (inferenceRouting.reranker_server_id && !inferenceRouting.reranker_model) {
      setError("Vyberte platný reranker model na přiřazeném serveru.");
      return;
    }
    setIsSavingInference(true);
    try {
      const saved = await updateInferenceConfiguration(inferenceRouting);
      setInferenceConfiguration(saved);
      setInferenceRouting(saved.routing);
      const refreshedModels = await listModels();
      setModels(refreshedModels);
      const effectiveChatModel =
        refreshedModels.find((model) => model.name === defaultChatModel) ??
        refreshedModels.find((model) => model.selected) ??
        refreshedModels[0];
      setSelectedModel(effectiveChatModel?.name ?? "");
    } catch (err) {
      setError(err instanceof Error ? err.message : "Uložení výpočetních serverů selhalo");
    } finally {
      setIsSavingInference(false);
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
    try {
      let conversation = activeConversation;
      if (!conversation) {
        conversation = await createConversation(content.slice(0, 80));
      }

      const response = await sendMessage(conversation.id, content, selectedModel || undefined);
      promoteConversation(response.conversation);
      setMessageInput("");
    } catch (err) {
      setError(err instanceof Error ? err.message : "Odeslani zpravy selhalo");
      return;
    } finally {
      setIsSending(false);
    }
  }

  function stopDialTone() {
    const controller = dialToneRef.current;
    if (!controller) {
      return;
    }
    window.clearInterval(controller.intervalId);
    dialToneRef.current = null;
    void controller.context.close();
  }

  function startDialTone() {
    stopDialTone();
    const AudioContextConstructor =
      window.AudioContext ??
      (window as typeof window & { webkitAudioContext?: typeof AudioContext }).webkitAudioContext;
    if (!AudioContextConstructor) {
      return;
    }

    const context = new AudioContextConstructor();
    const playPulse = () => {
      if (context.state === "closed") {
        return;
      }
      const now = context.currentTime;
      const oscillator = context.createOscillator();
      const gain = context.createGain();
      oscillator.type = "sine";
      oscillator.frequency.setValueAtTime(425, now);
      gain.gain.setValueAtTime(0.0001, now);
      gain.gain.exponentialRampToValueAtTime(0.035, now + 0.03);
      gain.gain.setValueAtTime(0.035, now + 0.9);
      gain.gain.exponentialRampToValueAtTime(0.0001, now + 1);
      oscillator.connect(gain);
      gain.connect(context.destination);
      oscillator.start(now);
      oscillator.stop(now + 1.05);
    };

    void context.resume().then(playPulse);
    const intervalId = window.setInterval(playPulse, 4_000);
    dialToneRef.current = { context, intervalId };
  }

  function handleVoiceStatus(payload: unknown) {
    const data = asRecord(payload);
    if (!data || data.type !== "voice_status") {
      return;
    }
    const state = typeof data.state === "string" ? data.state : "";
    if (state === "muted") {
      setIsVoiceMuted(true);
    } else if (state === "unmuted") {
      setIsVoiceMuted(false);
      setVoiceState("listening");
    }
    if (state === "listening" || state === "error" || state === "ended") {
      stopDialTone();
    }
    if (state === "connecting" || state === "listening" || state === "thinking" || state === "speaking" || state === "error" || state === "ended") {
      setVoiceState(state);
    } else if (state === "asr_result") {
      setVoiceState("recognizing");
    } else if (state === "assistant_response") {
      setVoiceState("speaking");
    }
    const transcript = voiceTranscriptFromPayload(data);
    if (transcript) {
      setVoiceTranscript(transcript);
    }
    if (typeof data.answer === "string") {
      setVoiceAnswer(data.answer);
    }
    if (Array.isArray(data.sources)) {
      setVoiceSources(data.sources as ChatSource[]);
    }
    if (typeof data.message === "string") {
      if (state === "error") {
        setVoiceError(data.message);
      }
    }
    const conversation = asRecord(data.conversation);
    if (conversation) {
      const messages = Array.isArray(conversation.messages) ? conversation.messages : [];
      const lastUserMessage = [...messages]
        .reverse()
        .map(asRecord)
        .find((message) => message?.role === "user" && typeof message.content === "string");
      if (typeof lastUserMessage?.content === "string" && lastUserMessage.content.trim()) {
        setVoiceTranscript(lastUserMessage.content.trim());
      }
      promoteConversation(conversation as ConversationDetail);
    }
  }

  async function handleStartVoiceCall() {
    if (!user || voiceSessionId) {
      return;
    }
    setActiveView("chat");
    setError(null);
    setVoiceError(null);
    setVoiceTranscript("");
    setVoiceAnswer("");
    setVoiceSources([]);
    setIsVoiceMuted(false);
    setVoiceState("connecting");
    startDialTone();
    try {
      if (!navigator.mediaDevices?.getUserMedia) {
        throw new Error("Prohlížeč nepodporuje přístup k mikrofonu.");
      }
      const microphoneStream = await navigator.mediaDevices.getUserMedia({ audio: true });
      microphoneStream.getTracks().forEach((track) => track.stop());
      const session = await createVoiceSession(activeConversation?.id ?? null);
      setVoiceSessionId(session.voice_session_id);
      promoteConversation(session.conversation);
      await loadSpeechCloudScript();
      if (!window.SpeechCloud) {
        throw new Error("SpeechCloud klient neni dostupny.");
      }
      const speechCloud = new window.SpeechCloud({
        uri: import.meta.env.VITE_SPEECHCLOUD_MODEL_URI ?? "https://speechcloud.kky.zcu.cz:9443/v1/speechcloud/edu-hds-all",
        tts: "#voice-audioout",
        local_dm: import.meta.env.VITE_SPEECH_DIALOG_LOCAL_DM ?? "ws://localhost:8888/ws"
      });
      let voiceTokenSent = false;
      let voiceAttached = false;
      let speechCloudSessionStarted = false;
      let localDialogManagerConnected = false;
      let voiceTokenRetry: number | null = null;
      const clearVoiceTokenRetry = () => {
        if (voiceTokenRetry !== null) {
          window.clearTimeout(voiceTokenRetry);
          voiceTokenRetry = null;
        }
      };
      const queueVoiceToken = (force = false) => {
        clearVoiceTokenRetry();
        voiceTokenRetry = window.setTimeout(() => sendVoiceToken(force), 250);
      };
      const sendVoiceToken = (force = false) => {
        if (voiceTokenSent && !force) {
          return;
        }
        if (!speechCloudSessionStarted || !localDialogManagerConnected) {
          queueVoiceToken(force);
          return;
        }
        try {
          speechCloud.dm_send_message({ data: { type: "voice_session", token: session.token } });
          voiceTokenSent = true;
        } catch {
          voiceTokenSent = false;
          queueVoiceToken(force);
        }
      };
      const attachTimeout = window.setTimeout(() => {
        if (!voiceAttached) {
          stopDialTone();
          setVoiceError("SpeechCloud se nepodařilo propojit s hlasovým dialogem.");
          setVoiceState("error");
        }
      }, 15_000);
      const handleSpeechCloudConnectionError = (message: unknown, fallback: string) => {
        window.clearTimeout(attachTimeout);
        stopDialTone();
        const record = asRecord(message);
        const detail = record?.error ?? record?.text ?? record?.reason ?? record?.status;
        setVoiceError(detail === undefined || detail === "" ? fallback : `${fallback}: ${String(detail)}`);
        setVoiceState("error");
      };
      speechCloudRef.current = speechCloud;
      speechCloud.on("ws_connected", () => setVoiceState("connecting"));
      speechCloud.on("ws_local_dm_connected", () => {
        localDialogManagerConnected = true;
        setVoiceState("connecting");
        sendVoiceToken();
      });
      speechCloud.on("error_init", (message) => {
        handleSpeechCloudConnectionError(message, "Inicializace SpeechCloudu selhala");
      });
      speechCloud.on("ws_error_init", (message) => {
        handleSpeechCloudConnectionError(message, "Nepodařilo se připojit ke SpeechCloudu");
      });
      speechCloud.on("ws_local_dm_error_init", (message) => {
        handleSpeechCloudConnectionError(message, "Nepodařilo se připojit k hlasovému dialogu");
      });
      speechCloud.on("ws_error", (message) => {
        handleSpeechCloudConnectionError(message, "Spojení se SpeechCloudem selhalo");
      });
      speechCloud.on("sc_start_session", () => {
        speechCloudSessionStarted = true;
        sendVoiceToken();
      });
      speechCloud.on("dm_receive_message", (message) => {
        const record = asRecord(message);
        const firstData = asRecord(record?.data);
        const data = firstData?.type === "voice_status" ? firstData : asRecord(firstData?.data);
        if (data?.state === "connecting" && !voiceAttached) {
          localDialogManagerConnected = true;
          sendVoiceToken(true);
        }
        if (data?.state === "listening") {
          voiceAttached = true;
          window.clearTimeout(attachTimeout);
        }
        handleVoiceStatus(data ?? record?.data);
      });
      speechCloud.on("asr_recognizing", () => {
        stopDialTone();
        setVoiceState("listening");
      });
      speechCloud.on("asr_result", (message) => {
        const transcript = voiceTranscriptFromPayload(message);
        if (transcript) {
          setVoiceTranscript(transcript);
        }
      });
      speechCloud.on("tts_done", () => {
        setVoiceState((current) => (current === "speaking" ? "listening" : current));
      });
      speechCloud.on("ws_closed", () => {
        window.clearTimeout(attachTimeout);
        clearVoiceTokenRetry();
        stopDialTone();
        setIsVoiceMuted(false);
        setVoiceState((current) => (current === "ended" ? current : "idle"));
        speechCloudRef.current = null;
      });
      speechCloud.on("sc_error", (message) => {
        window.clearTimeout(attachTimeout);
        clearVoiceTokenRetry();
        stopDialTone();
        const record = asRecord(message);
        setVoiceError(typeof record?.error === "string" ? record.error : "SpeechCloud chyba");
        setVoiceState("error");
      });
      speechCloud.init();
    } catch (err) {
      stopDialTone();
      setVoiceError(err instanceof Error ? err.message : "Spusteni hlasoveho hovoru selhalo");
      setVoiceState("error");
    }
  }

  async function handleEndVoiceCall() {
    const sessionId = voiceSessionId;
    stopDialTone();
    setIsVoiceMuted(false);
    speechCloudRef.current?.terminate();
    speechCloudRef.current = null;
    setVoiceSessionId(null);
    setVoiceState("ended");
    if (sessionId) {
      try {
        await endVoiceSession(sessionId);
      } catch (err) {
        setVoiceError(err instanceof Error ? err.message : "Ukonceni hlasove session selhalo");
        setVoiceState("error");
      }
    }
  }

  function handleStopVoiceTts() {
    speechCloudRef.current?.tts_stop();
  }

  function handleToggleVoiceMute() {
    const speechCloud = speechCloudRef.current;
    if (!speechCloud || !voiceSessionId) {
      return;
    }
    const nextMuted = !isVoiceMuted;
    speechCloud.dm_send_message({
      data: { type: "voice_control", action: nextMuted ? "mute" : "unmute" }
    });
    setIsVoiceMuted(nextMuted);
  }

  function handleVoiceOverlayPointerDown(event: ReactPointerEvent<HTMLDivElement>) {
    if (event.button !== 0 || !voiceOverlayRef.current) {
      return;
    }
    const bounds = voiceOverlayRef.current.getBoundingClientRect();
    voiceOverlayDragRef.current = {
      pointerId: event.pointerId,
      x: event.clientX - bounds.left,
      y: event.clientY - bounds.top
    };
    event.currentTarget.setPointerCapture(event.pointerId);
    event.preventDefault();
  }

  function handleVoiceOverlayPointerMove(event: ReactPointerEvent<HTMLDivElement>) {
    const drag = voiceOverlayDragRef.current;
    const overlay = voiceOverlayRef.current;
    if (!drag || drag.pointerId !== event.pointerId || !overlay) {
      return;
    }
    const margin = 8;
    setVoiceOverlayPosition({
      x: Math.min(Math.max(margin, event.clientX - drag.x), Math.max(margin, window.innerWidth - overlay.offsetWidth - margin)),
      y: Math.min(Math.max(margin, event.clientY - drag.y), Math.max(margin, window.innerHeight - overlay.offsetHeight - margin))
    });
    event.preventDefault();
  }

  function handleVoiceOverlayPointerUp(event: ReactPointerEvent<HTMLDivElement>) {
    if (voiceOverlayDragRef.current?.pointerId !== event.pointerId) {
      return;
    }
    voiceOverlayDragRef.current = null;
    if (event.currentTarget.hasPointerCapture(event.pointerId)) {
      event.currentTarget.releasePointerCapture(event.pointerId);
    }
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
          <form className="auth-form" onSubmit={handleAuth}>
            <label>
              Email
              <input
                value={email}
                onChange={(event) => setEmail(event.target.value)}
                type="email"
                autoComplete="email"
                required
              />
            </label>
            <label>
              Heslo
              <input
                value={password}
                onChange={(event) => setPassword(event.target.value)}
                type="password"
                autoComplete={authMode === "login" ? "current-password" : "new-password"}
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
            <button
              className="voice-call-button"
              onClick={handleStartVoiceCall}
              type="button"
              disabled={voiceState !== "idle" && voiceState !== "ended" && voiceState !== "error"}
              title="Spustit hlasový hovor"
            >
              <PhoneCall size={18} />
              Hovor
            </button>
            <span className={`voice-pill ${voiceState}`} aria-live="polite">
              <Mic size={18} />
              {voiceLabel}
            </span>
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
                {renderMarkdown(message.content)}
                {message.role === "assistant" && message.retrieval ? (
                  <div className="message-retrieval" aria-label="Pouzite vyhledavani">
                    {message.retrieval.used_rag && <b>used rag</b>}
                    {message.retrieval.used_search && <b>used search</b>}
                    {message.retrieval.used_reranker && <b>used reranker</b>}
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
                  {activeDocumentFile ? (
                    <div className="document-preview-stage">
                      {activeDocumentFile.mime_type.startsWith("image/") ? (
                        <figure className="document-image-preview">
                          <img
                            src={documentFileDownloadUrl(activeDocument.id, activeDocumentFile.id)}
                            alt={activeDocumentFile.filename}
                          />
                          <figcaption>{activeDocumentFile.filename}</figcaption>
                        </figure>
                      ) : (
                        <div className="document-preview-placeholder">
                          <FileText size={28} />
                          <span>{activeDocumentFile.filename}</span>
                          <a
                            className="ghost-button"
                            href={documentFileDownloadUrl(activeDocument.id, activeDocumentFile.id)}
                            target="_blank"
                            rel="noreferrer"
                          >
                            Otevrit soubor
                          </a>
                        </div>
                      )}
                    </div>
                  ) : null}
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
                          <div className={`document-file-row ${activeDocumentFile?.id === file.id ? "active" : ""}`} key={file.id}>
                            <button
                              className="document-file-select"
                              onClick={() => setActiveDocumentFileId(file.id)}
                              type="button"
                            >
                              <FileText size={16} />
                              <span>{file.sort_order + 1}. {file.filename}</span>
                            </button>
                            <span>
                              {file.mime_type}
                            </span>
                            <a
                              className="ghost-button icon-button"
                              href={documentFileDownloadUrl(activeDocument.id, file.id)}
                              download={file.filename}
                              aria-label="Stahnout soubor"
                              title="Stahnout soubor"
                            >
                              <Download size={16} />
                            </a>
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
                        <span>Zatim bez souboru dokladu.</span>
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
          {inferenceConfiguration && inferenceRouting ? (
            <section className="settings-section inference-settings" aria-labelledby="inference-heading">
              <div className="inference-settings-head">
                <div>
                  <h2 id="inference-heading">Výpočetní servery</h2>
                  <p>Role lze přetáhnout mezi servery nebo změnit jejich výběr přímo.</p>
                </div>
                <button
                  className="primary-button"
                  type="button"
                  onClick={handleSaveInference}
                  disabled={isSavingInference}
                >
                  <Save size={17} />
                  {isSavingInference ? "Ukládám" : "Uložit routing"}
                </button>
              </div>
              <div className="inference-server-grid">
                {inferenceConfiguration.servers.map((server) => (
                  <div
                    className="inference-server"
                    key={server.id}
                    onDragOver={(event) => event.preventDefault()}
                    onDrop={(event) => handleInferenceDrop(event, server.id)}
                  >
                    <div className="inference-server-head">
                      <Server size={19} />
                      <div>
                        <strong>{server.name}</strong>
                        <span className={server.reachable ? "server-online" : "server-offline"}>
                          {server.reachable ? `Dostupný · ${server.models.length} modelů` : "Nedostupný"}
                        </span>
                      </div>
                    </div>
                    <div className="inference-role-list">
                      {INFERENCE_ROLES.filter(
                        (role) =>
                          inferenceRouting[`${role.id}_server_id` as keyof InferenceRouting] === server.id
                      ).map((role) => (
                        <div
                          className="inference-role"
                          draggable
                          key={role.id}
                          onDragStart={(event) => {
                            event.dataTransfer.setData("application/x-sp2-inference-role", role.id);
                            event.dataTransfer.effectAllowed = "move";
                          }}
                        >
                          <GripVertical size={17} aria-hidden="true" />
                          <div>
                            <strong>{role.label}</strong>
                            <span>{role.description}</span>
                          </div>
                          <div className="inference-role-controls">
                            <select
                              aria-label={`Server pro ${role.label}`}
                              value={server.id}
                              onChange={(event) => assignInferenceRole(role.id, event.target.value || null)}
                            >
                              {role.id === "reranker" ? <option value="">Vypnuto</option> : null}
                              {inferenceConfiguration.servers.map((option) => (
                                <option key={option.id} value={option.id}>
                                  {option.name}
                                </option>
                              ))}
                            </select>
                            {role.id === "embedding" || role.id === "reranker" ? (
                              <select
                                aria-label={`Model pro ${role.label}`}
                                value={
                                  role.id === "embedding"
                                    ? inferenceRouting.embedding_model ?? ""
                                    : inferenceRouting.reranker_model ?? ""
                                }
                                onChange={(event) =>
                                  setInferenceRouting((current) =>
                                    current
                                      ? {
                                          ...current,
                                          [role.id === "embedding" ? "embedding_model" : "reranker_model"]:
                                            event.target.value || null
                                        }
                                      : current
                                  )
                                }
                              >
                                <option value="">Vyberte model</option>
                                {server.models.map((model) => (
                                  <option key={model} value={model}>
                                    {model}
                                  </option>
                                ))}
                              </select>
                            ) : null}
                          </div>
                        </div>
                      ))}
                    </div>
                  </div>
                ))}
              </div>
              {!inferenceRouting.reranker_server_id ? (
                <div className="inference-disabled-role">
                  <div>
                    <strong>Reranking je vypnutý</strong>
                    <span>
                      {inferenceConfiguration.reranker_enabled
                        ? "Vyberte server pro jeho zapnutí."
                        : "Nejdříve nastavte RAG_RERANKER_MODEL v .env."}
                    </span>
                  </div>
                  <select
                    aria-label="Server pro Reranking"
                    value=""
                    disabled={!inferenceConfiguration.reranker_enabled}
                    onChange={(event) => assignInferenceRole("reranker", event.target.value || null)}
                  >
                    <option value="">Vypnuto</option>
                    {inferenceConfiguration.servers.map((server) => (
                      <option key={server.id} value={server.id}>
                        {server.name}
                      </option>
                    ))}
                  </select>
                </div>
              ) : null}
            </section>
          ) : null}
            <section className="settings-section">
              <div>
                <h2>Chat</h2>
                <p>Tento model se automaticky vybere pro textový i hlasový chat.</p>
              </div>
              <label className="settings-field">
                <span>Výchozí model chatu</span>
                <select
                  value={defaultChatModel}
                  onChange={(event) => setDefaultChatModel(event.target.value)}
                  disabled={isSavingSettings}
                >
                  <option value="">Výchozí model serveru</option>
                  {models.map((model) => (
                    <option key={model.name} value={model.name}>
                      {model.name}
                    </option>
                  ))}
                  {defaultChatModel && !models.some((model) => model.name === defaultChatModel) ? (
                    <option value={defaultChatModel}>{defaultChatModel}</option>
                  ) : null}
                </select>
              </label>
              <div className="settings-current">
                <span>Aktuálně uloženo</span>
                <strong>{userSettings?.default_chat_model ?? "Výchozí model serveru"}</strong>
              </div>
            </section>
            <section className="settings-section">
              <div>
                <h2>Hlasový hovor</h2>
                <p>Zvolený hlas se použije pro uvítání i všechny odpovědi SpeechCloudu.</p>
              </div>
              <label className="settings-field">
                <span>TTS hlas</span>
                <select
                  value={ttsVoice}
                  onChange={(event) => setTtsVoice(event.target.value)}
                  disabled={isSavingSettings}
                >
                  <option value="">Výchozí hlas SpeechCloudu</option>
                  {TTS_VOICES.map((voice) => (
                    <option key={voice.value} value={voice.value}>
                      {voice.label}
                    </option>
                  ))}
                </select>
              </label>
              <div className="settings-current">
                <span>Aktuálně uloženo</span>
                <strong>
                  {TTS_VOICES.find((voice) => voice.value === userSettings?.tts_voice)?.label ??
                    "Výchozí hlas SpeechCloudu"}
                </strong>
              </div>
            </section>
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
                  {structuringModels.map((model) => (
                    <option key={model} value={model}>
                      {model}
                    </option>
                  ))}
                  {ocrProcessingModel && !structuringModels.includes(ocrProcessingModel) ? (
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
                  <span>Reranker best band</span>
                  <input
                    type="number"
                    min="0"
                    max="1"
                    step="0.01"
                    value={ragRerankerBestBand}
                    onChange={(event) => setRagRerankerBestBand(event.target.value)}
                    disabled={
                      isSavingSettings ||
                      ragSourceStrategy !== "best_band" ||
                      !inferenceRouting?.reranker_server_id
                    }
                  />
                </label>
                <label className="settings-field">
                  <span>Minimální reranker skóre</span>
                  <input
                    type="number"
                    min="0"
                    max="1"
                    step="0.05"
                    value={ragRerankerMinScore}
                    onChange={(event) => setRagRerankerMinScore(event.target.value)}
                    disabled={isSavingSettings || !inferenceRouting?.reranker_server_id}
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
                    : `Cosine ${userSettings?.rag_best_band ?? 0.08} · reranker ${userSettings?.rag_reranker_best_band ?? 0.10} · minimum ${userSettings?.rag_reranker_min_score ?? 0.50}`}
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
      {voiceSessionId || voiceState === "connecting" || voiceState === "error" ? (
        <div
          ref={voiceOverlayRef}
          className="voice-overlay"
          role="dialog"
          aria-label="Hlasový hovor"
          style={
            voiceOverlayPosition
              ? { left: voiceOverlayPosition.x, top: voiceOverlayPosition.y, right: "auto", bottom: "auto" }
              : undefined
          }
        >
          <div
            className="voice-overlay-head"
            onPointerDown={handleVoiceOverlayPointerDown}
            onPointerMove={handleVoiceOverlayPointerMove}
            onPointerUp={handleVoiceOverlayPointerUp}
            onPointerCancel={handleVoiceOverlayPointerUp}
          >
            <div>
              <p className="eyebrow">SpeechCloud hovor</p>
              <h2>{voiceLabel}</h2>
            </div>
            <Mic size={22} />
          </div>
          <div className="voice-overlay-body">
            <div>
              <span>Poslední dotaz</span>
              <strong>{voiceTranscript || "Čekám na hlasový vstup..."}</strong>
            </div>
            <div>
              <span>Odpověď</span>
              <p>{voiceAnswer || "Odpověď se zobrazí po zpracování dotazu."}</p>
            </div>
            {voiceSources.length ? (
              <div className="voice-overlay-sources">
                <span>Zdroje</span>
                {voiceSources.map((source) => (
                  <button key={source.document_id} type="button" onClick={() => handleOpenDocumentSource(source.document_id)}>
                    <FileText size={14} />
                    {source.title}
                  </button>
                ))}
              </div>
            ) : null}
            {voiceError && <p className="error-text">{voiceError}</p>}
          </div>
          <div className="voice-overlay-actions">
            <button className="ghost-button" type="button" onClick={handleStopVoiceTts}>
              Stop TTS
            </button>
            <button
              className={`ghost-button icon-button voice-mute-button ${isVoiceMuted ? "active" : ""}`}
              type="button"
              onClick={handleToggleVoiceMute}
              disabled={!voiceSessionId || voiceState === "connecting" || voiceState === "error"}
              aria-label={isVoiceMuted ? "Zapnout mikrofon" : "Ztlumit mikrofon"}
              title={isVoiceMuted ? "Zapnout mikrofon" : "Ztlumit mikrofon"}
            >
              {isVoiceMuted ? <MicOff size={19} /> : <Mic size={19} />}
            </button>
            <button
              className="danger-button icon-button voice-end-button"
              type="button"
              onClick={handleEndVoiceCall}
              aria-label="Ukončit hovor"
              title="Ukončit hovor"
            >
              <PhoneOff size={19} />
            </button>
          </div>
          <audio id="voice-audioout" />
        </div>
      ) : null}
    </main>
  );
}
