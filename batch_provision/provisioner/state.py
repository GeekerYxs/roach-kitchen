"""Per-account persistent record (state/<account>.json). Never stores passwords."""
import json
import threading
import time
from pathlib import Path

CREATED, EXISTS, FAILED, UNCERTAIN = 'created', 'exists', 'failed', 'uncertain'
NO_SLOT = 'no_slot'  # not attempted: the account's 4 slots are taken (some by other programs)


class AccountState:
    def __init__(self, folder, account):
        self.path = Path(folder) / f'{account}.json'
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.Lock()
        self.data = json.loads(self.path.read_text('utf-8')) if self.path.is_file() else {'account': account, 'roles': {}}

    def role(self, name):
        return self.data['roles'].get(name, {})

    def is_done(self, name):
        return self.role(name).get('status') in (CREATED, EXISTS)

    def set_role(self, name, status, **fields):
        with self._lock:
            self.data['roles'][name] = {'status': status, 'time': time.strftime('%Y-%m-%d %H:%M:%S'), **fields}
            self._save()

    def update(self, **fields):
        with self._lock:
            self.data.update(fields)
            self._save()

    def _save(self):
        tmp = self.path.with_suffix('.tmp')
        tmp.write_text(json.dumps(self.data, ensure_ascii=False, indent=2), 'utf-8')
        tmp.replace(self.path)
