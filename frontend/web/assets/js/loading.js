(function () {
  function $(id) { return document.getElementById(id); }
  function qs(name) { try { return new URLSearchParams(window.location.search).get(name); } catch (_) { return null; } }

  var job = qs('job');
  var titleEl = $('loadingTitle');
  var subtitleEl = $('loadingSubtitle');
  var backEl = $('loadingBack');

  function showError(msg) {
    if (titleEl) titleEl.textContent = 'Something went wrong';
    if (subtitleEl) subtitleEl.textContent = msg || 'Request failed.';
    if (backEl) backEl.classList.remove('hidden');
  }

  if (!job) {
    showError('Missing job id. Go back and try again.');
    return;
  }

  var stopped = false;
  var startedAt = Date.now();

  async function poll() {
    if (stopped) return;
    if (Date.now() - startedAt > 10 * 60 * 1000) { // 10 minutes
      showError('This is taking longer than expected. Please try again.');
      stopped = true;
      return;
    }
    try {
      var res = await fetch('/api/job/' + encodeURIComponent(job) + '?ts=' + Date.now());
      var data = {};
      try { data = await res.json(); } catch (_) {}
      if (!res.ok || !data || !data.ok) {
        throw new Error((data && data.error) ? data.error : 'Job not found.');
      }

      var status = data.status;
      if (status === 'done') {
        var next = data.next || '/';
        window.location.href = next;
        return;
      }
      if (status === 'error') {
        showError(data.error || 'Request failed.');
        stopped = true;
        return;
      }
    } catch (err) {
      // transient error; keep polling
    }
    setTimeout(poll, 800);
  }

  poll();
})();

