import unittest
from asyncio import gather

from pulsar import (send, new_event_loop, get_application,
                    run_in_loop, get_event_loop)
from pulsar.apps.test import dont_run_with_thread

from examples.echo.manage import server, Echo, EchoServerProtocol


class TestEchoServerThread(unittest.TestCase):
    concurrency = 'thread'
    server_cfg = None

    @classmethod
    async def setUpClass(cls):
        s = server(name=cls.__name__.lower(), bind='127.0.0.1:0',
                   backlog=1024, concurrency=cls.concurrency)
        cls.server_cfg = await send('arbiter', 'run', s)
        cls.client = Echo(cls.server_cfg.addresses[0])

    @classmethod
    def tearDownClass(cls):
        if cls.server_cfg:
            return send('arbiter', 'kill_actor', cls.server_cfg.name)

    #    TEST THE SERVER APPLICATION
    async def test_server_on_arbiter(self):
        app = await get_application(self.__class__.__name__.lower())
        cfg = app.cfg
        self.assertTrue(cfg.addresses)
        self.assertTrue(cfg.address)
        self.assertNotEqual(cfg.addresses[0], cfg.address)

    def test_server(self):
        server = self.server_cfg.app()
        self.assertTrue(server)
        self.assertEqual(server.cfg.callable, EchoServerProtocol)
        self.assertTrue(server.cfg.addresses)

    #    TEST CLIENT INTERACTION
    async def test_ping(self):
        result = await self.client(b'ciao luca')
        self.assertEqual(result, b'ciao luca')

    async def test_large(self):
        '''Echo a 3MB message'''
        msg = b''.join((b'a' for x in range(2**13)))
        result = await self.client(msg)
        self.assertEqual(result, msg)

    async def test_multi(self):
        result = await gather(self.client(b'ciao'),
                              self.client(b'pippo'),
                              self.client(b'foo'))
        self.assertEqual(len(result), 3)
        self.assertTrue(b'ciao' in result)
        self.assertTrue(b'pippo' in result)
        self.assertTrue(b'foo' in result)

    # TESTS FOR PROTOCOLS AND CONNECTIONS
    async def test_client(self):
        await self.test_multi()
        c = self.client
        self.assertTrue(c.pool.available)

    async def test_info(self):
        info = await send(self.server_cfg.name, 'info')
        self.assertIsInstance(info, dict)
        self.assertEqual(info['actor']['name'], self.server_cfg.name)
        self.assertEqual(info['actor']['concurrency'], self.concurrency)

    async def test_connection(self):
        client = Echo(self.server_cfg.addresses[0], full_response=True)
        response = await client(b'test connection')
        self.assertEqual(response.buffer, b'test connection')
        connection = response.connection
        self.assertTrue(str(connection))

    async def test_connection_pool(self):
        '''Test the connection pool. A very important test!'''
        client = Echo(self.server_cfg.addresses[0], pool_size=2)
        self.assertEqual(client._loop, get_event_loop())
        #
        self.assertEqual(client.pool.pool_size, 2)
        self.assertEqual(client.pool.in_use, 0)
        self.assertEqual(client.pool.available, 0)
        self.assertEqual(client.sessions, 0)
        self.assertEqual(client._requests_processed, 0)
        #
        response = await client(b'test connection')
        self.assertEqual(response, b'test connection')
        self.assertEqual(client.pool.in_use, 0)
        self.assertEqual(client.pool.available, 1)
        self.assertEqual(client.sessions, 1)
        self.assertEqual(client._requests_processed, 1)
        #
        response = await client(b'test connection 2')
        self.assertEqual(response, b'test connection 2')
        self.assertEqual(client.pool.in_use, 0)
        self.assertEqual(client.pool.available, 1)
        self.assertEqual(client.sessions, 1)
        self.assertEqual(client._requests_processed, 2)
        #
        result = await gather(client(b'ciao'),
                              client(b'pippo'),
                              client(b'foo'))
        self.assertEqual(len(result), 3)
        self.assertTrue(b'ciao' in result)
        self.assertTrue(b'pippo' in result)
        self.assertTrue(b'foo' in result)
        self.assertEqual(client.pool.in_use, 0)
        self.assertEqual(client.pool.available, 2)
        self.assertEqual(client.sessions, 2)
        self.assertEqual(client._requests_processed, 5)
        #
        # drop a connection
        await run_in_loop(client._loop, self._drop_conection, client)
        #
        result = await gather(client(b'ciao'),
                              client(b'pippo'),
                              client(b'foo'))
        self.assertEqual(len(result), 3)
        self.assertEqual(client.pool.in_use, 0)
        self.assertEqual(client.pool.available, 2)
        self.assertEqual(client.sessions, 3)
        self.assertEqual(client._requests_processed, 8)
        #
        await run_in_loop(client._loop, client.pool.close)
        #
        self.assertEqual(client.pool.in_use, 0)
        self.assertEqual(client.pool.available, 0)
        self.assertEqual(client.sessions, 3)
        self.assertEqual(client._requests_processed, 8)

    def _drop_conection(self, client):
        conn1 = client.pool._queue.get_nowait()
        conn1.close()
        conn2 = client.pool._queue.get_nowait()
        client.pool._queue.put_nowait(conn1)
        client.pool._queue.put_nowait(conn2)


@dont_run_with_thread
class TestEchoServerProcess(TestEchoServerThread):
    concurrency = 'process'

    def sync_client(self):
        return Echo(self.server_cfg.addresses[0], loop=new_event_loop())

    async def setUp(self):
        result = await self.client(b'ciao luca')
        self.assertEqual(result, b'ciao luca')

    #    TEST SYNCHRONOUS CLIENT
    def test_sync_echo(self):
        echo = self.sync_client()
        self.assertEqual(echo(b'ciao!'), b'ciao!')
        self.assertEqual(echo(b'fooooooooooooo!'),  b'fooooooooooooo!')

    async def test_sync_close(self):
        # TODO: fix this. Issue #251
        echo = self.sync_client()
        self.assertEqual(echo(b'ciao!'), b'ciao!')
        self.assertEqual(echo.sessions, 1)
        self.assertEqual(echo(b'QUIT'), b'QUIT')
        self.assertEqual(echo.sessions, 1)
        # self.assertEqual(echo(b'ciao!'), b'ciao!')
        # self.assertEqual(echo.sessions, 2)
