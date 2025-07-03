const API_URL = 'http://127.0.0.1:8000/review';
const BUTTON_ID = 'ai-code-review-button';

function initAICodeReview() {
  if (!window.location.pathname.includes('/-/merge_requests/')) return;
  waitForElement('.gl-button-group, .mr-state-container + div').then(addReviewButton);
}

function waitForElement(selector) {
  return new Promise(resolve => {
    if (document.querySelector(selector)) return resolve(document.querySelector(selector));
    const observer = new MutationObserver(() => {
      const el = document.querySelector(selector);
      if (el) {
        observer.disconnect();
        resolve(el);
      }
    });
    observer.observe(document.body, { childList: true, subtree: true });
  });
}

function addReviewButton() {
  if (document.getElementById(BUTTON_ID)) return;

  const button = document.createElement('button');
  button.id = BUTTON_ID;
  button.className = 'gl-button btn btn-confirm';
  button.innerText = '🤖 Genie Review';
  button.style.marginLeft = '8px';
  button.style.transition = 'background-color 0.3s ease';

  const container = document.querySelector('.gl-button-group') || document.querySelector('.mr-state-container + div');
  if (container) {
    container.appendChild(button);
    button.addEventListener('click', handleReviewButtonClick);
  }
}

async function handleReviewButtonClick() {
  const button = document.getElementById(BUTTON_ID);
  button.disabled = true;
  button.innerText = '🔄 Analyzing...';
  button.style.backgroundColor = '#dc3545';  // Red
  button.style.color = 'white';
  button.style.border = '1px solid #a71d2a';

  try {
    const mrData = getMergeRequestData();
    const response = await fetch(API_URL, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(mrData)
    });
    const result = await response.json();

    button.innerText = '✅ Review Complete';
    button.style.backgroundColor = '#28a745';  // Green
    button.style.border = '1px solid #1c7430';
  } catch (error) {
    alert('⚠️ Error during review: ' + (error.message || 'Unknown error'));
    button.innerText = '❌ Failed';
    button.style.backgroundColor = '#6c757d';  // Gray
    button.style.border = '1px solid #5a6268';
  } finally {
    setTimeout(() => {
      button.disabled = false;
      button.innerText = '🤖 Genie Review';
      button.style.backgroundColor = '#007bff';  // Reset to blue
      button.style.border = '1px solid #007bff';
    }, 3000);
  }
}

function getMergeRequestData() {
  const pathParts = window.location.pathname.split('/-/');
  const projectPath = pathParts[0].substring(1);
  const mrMatch = window.location.pathname.match(/\/merge_requests\/(\d+)/);
  const mrIid = mrMatch ? mrMatch[1] : null;
  return { project_path: projectPath, merge_request_iid: mrIid };
}

initAICodeReview();