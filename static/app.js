const lessonForm = document.getElementById("lesson-form");
const topicInput = document.getElementById("topic");
const dialectSelect = document.getElementById("dialect");
const bookInput = document.getElementById("book");
const lessonSection = document.getElementById("lesson-section");
const overviewGrid = document.getElementById("overview");
const startLessonBtn = document.getElementById("start-lesson");
const exerciseSection = document.getElementById("exercise-section");
const exerciseCard = document.getElementById("exercise-card");
const formStatus = document.getElementById("form-status");
const progressPill = document.getElementById("progress-pill");

const state = {
  lesson: null,
  currentIndex: 0,
  audioCache: new Map(),
  loadingAudio: new Set(),
};

async function readBookFile(file) {
  return new Promise((resolve, reject) => {
    const reader = new FileReader();
    reader.onload = () => resolve(reader.result);
    reader.onerror = () => reject(reader.error);
    reader.readAsText(file);
  });
}

function setStatus(message, isError = false) {
  formStatus.textContent = message;
  formStatus.style.color = isError ? "#ff9c9c" : "#a2adbc";
}

async function createLesson(event) {
  event.preventDefault();
  setStatus("Generating lesson...");

  let bookText = null;
  if (bookInput.files && bookInput.files[0]) {
    try {
      bookText = await readBookFile(bookInput.files[0]);
    } catch (error) {
      console.error(error);
      setStatus("Could not read the uploaded file", true);
      return;
    }
  }

  const payload = {
    topic: topicInput.value.trim(),
    dialect: dialectSelect.value,
    book_text: bookText,
  };

  try {
    const response = await fetch("/api/lesson", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload),
    });
    if (!response.ok) {
      throw new Error(`Request failed: ${response.status}`);
    }
    const data = await response.json();
    state.lesson = data;
    state.currentIndex = 0;
    state.audioCache.clear();
    state.loadingAudio.clear();
    renderOverview();
    setStatus("Lesson ready! Start when you like.");
    lessonSection.hidden = false;
    exerciseSection.hidden = false;
    updateProgress();
    renderExercise();
  } catch (error) {
    console.error(error);
    setStatus("Could not generate lesson. Please try again.", true);
  }
}

function renderOverview() {
  overviewGrid.innerHTML = "";
  const { exercises, topic, dialect } = state.lesson;
  exercises.forEach((exercise) => {
    const card = document.createElement("div");
    card.className = "card";
    card.innerHTML = `
      <div class="card__id">Exercise ${exercise.id}</div>
      <div class="muted">${exercise.translation_hint}</div>
      <div>${exercise.swiss_sentence}</div>
    `;
    overviewGrid.appendChild(card);
  });

  startLessonBtn.onclick = () => {
    state.currentIndex = 0;
    renderExercise();
  };
}

function updateProgress() {
  if (!state.lesson) return;
  progressPill.textContent = `Exercise ${state.currentIndex + 1} of ${state.lesson.exercises.length}`;
}

async function fetchAudioFor(text) {
  if (state.audioCache.has(text) || state.loadingAudio.has(text)) {
    return;
  }
  state.loadingAudio.add(text);
  try {
    const response = await fetch("/api/audio", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ text, dialect: dialectSelect.value }),
    });
    if (!response.ok) {
      throw new Error("Audio request failed");
    }
    const { audio_base64, content_type } = await response.json();
    const binary = Uint8Array.from(atob(audio_base64), (c) => c.charCodeAt(0));
    const blob = new Blob([binary], { type: content_type });
    const url = URL.createObjectURL(blob);
    state.audioCache.set(text, url);
  } catch (error) {
    console.error("Audio fetch failed", error);
  } finally {
    state.loadingAudio.delete(text);
  }
}

async function prefetchAudio(index) {
  if (!state.lesson) return;
  const exercise = state.lesson.exercises[index];
  if (!exercise) return;
  await fetchAudioFor(exercise.swiss_sentence);
}

async function handleListen(text, button) {
  button.disabled = true;
  button.textContent = "Loading audio...";
  await fetchAudioFor(text);
  const url = state.audioCache.get(text);
  if (url) {
    const audio = new Audio(url);
    audio.play();
    button.textContent = "Listen";
  } else {
    button.textContent = "Listen";
    button.title = "Audio unavailable";
  }
  button.disabled = false;
}

function renderExercise() {
  if (!state.lesson) return;
  const exercise = state.lesson.exercises[state.currentIndex];
  if (!exercise) return;

  updateProgress();
  exerciseCard.innerHTML = "";

  const prompt = document.createElement("div");
  prompt.className = "prompt";
  prompt.textContent = exercise.swiss_sentence;

  const hint = document.createElement("div");
  hint.className = "muted";
  hint.textContent = exercise.translation_hint;

  const textarea = document.createElement("textarea");
  textarea.placeholder = "Type your translation here...";

  const listenBtn = document.createElement("button");
  listenBtn.className = "button button--ghost";
  listenBtn.textContent = "Listen";
  listenBtn.type = "button";
  listenBtn.addEventListener("click", () => handleListen(exercise.swiss_sentence, listenBtn));

  const showAnswer = document.createElement("button");
  showAnswer.className = "button button--ghost";
  showAnswer.textContent = "Show reference";
  showAnswer.type = "button";

  const feedback = document.createElement("div");
  feedback.className = "feedback hidden";
  feedback.textContent = exercise.reference_translation;

  showAnswer.addEventListener("click", () => {
    feedback.classList.remove("hidden");
  });

  const nextBtn = document.createElement("button");
  nextBtn.className = "button";
  nextBtn.textContent = state.currentIndex === state.lesson.exercises.length - 1 ? "Restart" : "Next";
  nextBtn.type = "button";
  nextBtn.addEventListener("click", () => {
    if (state.currentIndex >= state.lesson.exercises.length - 1) {
      state.currentIndex = 0;
    } else {
      state.currentIndex += 1;
    }
    renderExercise();
  });

  const footer = document.createElement("div");
  footer.className = "footer-actions";
  footer.append(listenBtn, showAnswer, nextBtn);

  const tags = document.createElement("div");
  tags.className = "tag-row";
  tags.innerHTML = `<span class="tag">Dialect: ${state.lesson.dialect}</span><span class="tag">Prefetching next audio</span>`;

  exerciseCard.append(prompt, hint, textarea, feedback, footer, tags);

  prefetchAudio(state.currentIndex);
  prefetchAudio(state.currentIndex + 1);
}

lessonForm.addEventListener("submit", createLesson);
