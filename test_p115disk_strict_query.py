import ast
import sys
from pathlib import Path
from types import SimpleNamespace
from typing import Any, Dict, List, Optional, Tuple
from unittest import TestCase
from unittest.mock import MagicMock, patch


def _compile(path: Path, namespace: Dict[str, Any], class_name: str) -> Any:
    """
    从真实源码加载指定类，仅隔离宿主和网络导入边界

    :param path (Path): 待验证的真实源码路径
    :param namespace (Dict): 宿主构造与网络边界替身
    :param class_name (str): 待加载的类名

    :return Any: 加载后的真实业务类
    """
    tree = ast.parse(path.read_text())
    node = next(
        item for item in tree.body
        if isinstance(item, ast.ClassDef) and item.name == class_name
    )
    module = ast.Module(body=[
        ast.ImportFrom(module="__future__", names=[ast.alias(name="annotations")], level=0),
        node,
    ], type_ignores=[])
    exec(compile(ast.fix_missing_locations(module), str(path), "exec"), namespace)
    return namespace[class_name]

class QueryReceipt:
    """
    隔离宿主依赖的查询回执构造边界
    """

    def __init__(self, *, item: Any) -> None:
        """
        保存提供方已经确认的文件项

        :param item (Any): 查询到的文件项，确认缺失时为 None
        """
        self.item = item


class QueryError(Exception):
    """
    隔离宿主依赖的存储查询异常边界
    """


class TestV3P115DiskStrictQuery(TestCase):
    """
    验证整理后处理获得明确远端状态且不把缓存和错误当作当前文件
    """

    def setUp(self) -> None:
        """
        保留实际插件与 API 方法，仅隔离网络、日志和宿主构造边界
        """
        root = Path(__file__).resolve().parent / "plugins.v3/p115disk"
        schema = SimpleNamespace(FileItemQueryResult=QueryReceipt)
        imports = patch.dict(sys.modules, {"app.schemas.file": schema})
        imports.start()
        self.addCleanup(imports.stop)
        self.storage_chain = MagicMock()
        self.resolve = MagicMock()
        self.attributes = MagicMock()
        self.api_class = _compile(
            root / "p115_api.py",
            {
                "StorageQueryError": QueryError,
                "StorageChain": self.storage_chain,
                "logger": MagicMock(),
                "Path": Path,
                "FileItem": SimpleNamespace,
                "get_id_to_path": self.resolve,
                "get_attr": self.attributes,
                "get_ios_ua_app": lambda **kwargs: {},
                "monotonic": lambda: 0,
            },
            "P115Api",
        )
        self.api = object.__new__(self.api_class)
        self.api._disk_name = "115网盘Plus"
        self.api.client = MagicMock()
        self.api._id_cache = MagicMock()
        self.api._id_item_cache = MagicMock()
        self.api._get_item_fail_records = {}
        self.api._get_item_blacklist = {}
        self.api._get_item_rate_limiter = MagicMock()
        self.cached = SimpleNamespace(fileid="old", path="/video.mkv", size=10)
        self.current = SimpleNamespace(fileid="new", path="/video.mkv", size=20)
        self.api._get_cached_item = MagicMock(return_value=self.cached)
        self.api._query_item = MagicMock(return_value=self.current)
        self.plugin_class = _compile(
            root / "__init__.py",
            {
                "_PluginBase": object,
                "eventmanager": SimpleNamespace(register=lambda *args: lambda fn: fn),
                "ChainEventType": SimpleNamespace(StorageOperSelection="selection"),
                "FileItemQueryResult": QueryReceipt,
                "StorageQueryError": QueryError,
                "Path": Path,
            },
            "P115Disk",
        )
        self.plugin = object.__new__(self.plugin_class)
        self.plugin._disk_name = self.api._disk_name
        self.plugin._p115_api = self.api
        self.path = Path("/video.mkv")

    def test_module_provides_explicit_query_receipt(self) -> None:
        """
        宿主通过声明的严格提供方取得实际查询文件
        """
        provider = self.plugin.get_module()["get_file_item_strict"]
        receipt = provider(storage=self.api._disk_name, path=self.path)
        self.assertIsInstance(receipt, QueryReceipt)
        self.assertIs(receipt.item, self.current)

    def test_entry_definition_does_not_require_new_host_schema(self) -> None:
        """
        旧宿主缺少新回执模型时保留入口定义加载与普通查询
        """
        path = Path(__file__).resolve().parent / "plugins.v3/p115disk/__init__.py"
        tree = ast.parse(path.read_text())
        node = next(item for item in tree.body if isinstance(item, ast.ClassDef))
        namespace = self.plugin_class.get_file_item.__globals__.copy()
        namespace.pop("FileItemQueryResult", None)
        namespace.update(
            Any=Any, Dict=Dict, List=List, Optional=Optional, Tuple=Tuple,
            FileItem=SimpleNamespace, Event=SimpleNamespace,
            StorageUsage=SimpleNamespace, Response=SimpleNamespace,
        )
        # 不添加 future 注解，验证实际类定义的类型解析不会依赖新模型
        module = ast.Module(body=[node], type_ignores=[])
        exec(compile(ast.fix_missing_locations(module), str(path), "exec"), namespace)
        plugin = object.__new__(namespace["P115Disk"])
        plugin._disk_name, plugin._p115_api = self.plugin._disk_name, self.api
        with patch.dict(sys.modules, {"app.schemas.file": None}):
            self.assertIs(plugin.get_file_item(plugin._disk_name, self.path), self.cached)
            self.assertIsNone(plugin.get_file_item_strict("other-storage", self.path))

    def test_confirmed_missing_is_an_empty_receipt(self) -> None:
        """
        确认不存在与提供方不支持的空返回值保持区分
        """
        self.api._query_item.side_effect = FileNotFoundError("deleted")
        receipt = self.plugin.get_file_item_strict(self.api._disk_name, self.path)
        self.assertIsInstance(receipt, QueryReceipt)
        self.assertIsNone(receipt.item)

    def test_other_storage_is_declined_without_queries(self) -> None:
        """
        严格查询不接管其他存储
        """
        self.assertIsNone(self.plugin.get_file_item_strict("u115", self.path))
        self.api._query_item.assert_not_called()

    def test_uninitialized_provider_does_not_confirm_missing(self) -> None:
        """
        未初始化的已匹配存储不能确认文件不存在
        """
        self.plugin._p115_api = None
        with self.assertRaises(QueryError):
            self.plugin.get_file_item_strict(self.plugin._disk_name, self.path)

    def test_stale_positive_cache_cannot_hide_replacement(self) -> None:
        """
        同路径洗版后返回新身份，不返回旧正缓存
        """
        self.assertIs(self.api.get_item_strict(self.path), self.current)
        self.api._get_cached_item.assert_not_called()

    def test_stale_positive_cache_cannot_hide_deletion(self) -> None:
        """
        已删除目标即使仍有缓存也确认缺失
        """
        self.api._query_item.side_effect = FileNotFoundError("deleted")
        self.assertIsNone(self.api.get_item_strict(self.path))
        self.api._get_cached_item.assert_not_called()

    def test_negative_blacklist_does_not_hide_new_target(self) -> None:
        """
        普通查询的短时缺失黑名单不阻止整理完成后核验
        """
        self.api._get_item_blacklist[self.path.as_posix()] = 15
        self.assertIs(self.api.get_item_strict(self.path), self.current)

    def test_missing_parent_is_confirmed_absent(self) -> None:
        """
        实际路径遍历发现父项不是目录时确认目标缺失
        """
        self.api._query_item.side_effect = NotADirectoryError("parent is a file")
        self.assertIsNone(self.api.get_item_strict(self.path))
        self.storage_chain.assert_not_called()

    def test_fallback_uses_strict_host_query(self) -> None:
        """
        主查询故障时降级查询也必须提供明确回执
        """
        self.api._query_item.side_effect = TimeoutError("Web API timed out")
        native = SimpleNamespace(
            fileid="2", path="/video.mkv", size=20, modify_time=1,
            pickcode="pc", type="file",
            model_dump=lambda **kwargs: {
                "fileid": "2", "path": "/video.mkv", "size": 20,
                "modify_time": 1, "pickcode": "pc", "type": "file",
            },
        )
        self.storage_chain.return_value.get_file_item_strict.return_value = native
        item = self.api.get_item_strict(self.path)
        self.assertEqual((item.storage, item.fileid), (self.api._disk_name, "2"))
        self.storage_chain.return_value.get_file_item_strict.assert_called_once_with(
            storage="u115", path=self.path
        )
        self.storage_chain.return_value.get_file_item.assert_not_called()

    def test_confirmed_native_missing_is_not_an_unknown_state(self) -> None:
        """
        严格降级已确认缺失时允许返回空文件项
        """
        self.api._query_item.side_effect = TimeoutError("Web API timed out")
        self.storage_chain.return_value.get_file_item_strict.return_value = None
        self.assertIsNone(self.api.get_item_strict(self.path))
        self.storage_chain.return_value.get_file_item.assert_not_called()

    def test_native_query_failure_never_becomes_missing(self) -> None:
        """
        网络、限流、授权和缺失提供方错误均继续向宿主抛出
        """
        for error in (TimeoutError("timeout"), QueryError("no provider"), PermissionError("expired")):
            with self.subTest(error=type(error).__name__):
                self.api._query_item.side_effect = TimeoutError("Web API timed out")
                self.storage_chain.return_value.get_file_item_strict.side_effect = error
                with self.assertRaises(QueryError):
                    self.api.get_item_strict(self.path)

    def test_strict_path_resolution_ignores_old_directory_mapping(self) -> None:
        """
        旧父目录映射指向别处文件时重新遍历实际路径取得新目标
        """
        self.api._query_item = self.api_class._query_item.__get__(self.api)
        self.resolve.side_effect = lambda **kwargs: "new" if kwargs.get("refresh") else "old"
        self.attributes.side_effect = lambda **kwargs: {
            "id": kwargs["id"], "parent_id": 1, "name": "video.mkv",
            "size": 20, "mtime": 1, "pickcode": "pc", "is_dir": False,
        }
        result = self.api.get_item_strict(self.path)
        self.assertEqual(result.fileid, "new")

    def test_ordinary_query_keeps_positive_cache(self) -> None:
        """
        普通浏览查询保留缓存以避免无关等待增加
        """
        self.assertIs(self.api.get_item(self.path), self.cached)
        self.api._query_item.assert_not_called()
        self.api._get_item_rate_limiter.acquire.assert_not_called()
