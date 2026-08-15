from __future__ import annotations

import logging
import tempfile
import unittest
from pathlib import Path

from data_factory.core.logging import configure_logging

LOG = logging.getLogger("data_factory.tests.logging")


class ConfigureLoggingTests(unittest.TestCase):
    def setUp(self) -> None:
        self._temporary = tempfile.TemporaryDirectory()
        self.log_dir = Path(self._temporary.name) / "logs"
        self._saved = list(logging.getLogger().handlers)

    def tearDown(self) -> None:
        root = logging.getLogger()
        for handler in list(root.handlers):
            root.removeHandler(handler)
            handler.close()
        for handler in self._saved:
            root.addHandler(handler)
        self._temporary.cleanup()

    def _read(self, path: Path) -> str:
        for handler in logging.getLogger().handlers:
            handler.flush()
        return path.read_text(encoding="utf-8")

    def test_creates_log_file_and_records_messages(self) -> None:
        path = configure_logging(self.log_dir, "update")

        assert path is not None
        LOG.info("处理 adj_close.pkl")

        self.assertIn("处理 adj_close.pkl", self._read(path))

    def test_file_keeps_debug_even_without_verbose(self) -> None:
        """出问题之后再加 --verbose 重跑往往已经来不及，落盘的那份必须是全量。"""
        path = configure_logging(self.log_dir, "update", verbose=False)

        assert path is not None
        LOG.debug("跳过的无匹配文件: a.pkl")

        self.assertIn("跳过的无匹配文件", self._read(path))

    def test_repeated_setup_does_not_duplicate_output(self) -> None:
        configure_logging(self.log_dir, "update")
        path = configure_logging(self.log_dir, "update")

        assert path is not None
        LOG.info("只应出现一次")

        self.assertEqual(self._read(path).count("只应出现一次"), 1)

    def test_tag_marks_the_run_in_the_file_name(self) -> None:
        """校验跑和真正改过数据的那次，光看目录列表就该能分清。"""
        path = configure_logging(self.log_dir, "update", tag="dryrun")

        assert path is not None
        self.assertTrue(path.name.endswith("_dryrun.log"), path.name)

    def test_untagged_run_keeps_the_plain_name(self) -> None:
        path = configure_logging(self.log_dir, "convert")

        assert path is not None
        self.assertRegex(path.name, r"^convert_\d{8}_\d{6}_\d+\.log$")

    def test_log_dir_none_stays_console_only(self) -> None:
        self.assertIsNone(configure_logging(None, "update"))

    def test_unwritable_log_dir_does_not_abort(self) -> None:
        """日志落不了盘不该拦下整条命令。"""
        blocked = Path(self._temporary.name) / "blocked"
        blocked.write_text("", encoding="utf-8")

        self.assertIsNone(configure_logging(blocked / "logs", "update"))


if __name__ == "__main__":
    unittest.main()
