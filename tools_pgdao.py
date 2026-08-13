"""This file is part of Giswater
The program is free software: you can redistribute it and/or modify it under the terms of the GNU
General Public License as published by the Free Software Foundation, either version 3 of the License,
or (at your option) any later version.
"""

# -*- coding: utf-8 -*-
import psycopg2
import psycopg2.extras


class GwPgDao(object):
    APP_NAME_DAO = "giswater-dao"
    APP_NAME_AUX = "giswater-aux"

    def __init__(self):
        self.last_error = None
        self.set_search_path = None
        self.conn = None
        self.cursor = None
        self.pid = None

    def init_db(self):
        """Initializes database connection"""
        try:
            if self.conn is not None and not getattr(self.conn, "closed", True):
                self.close_db()
            self.conn = psycopg2.connect(self.conn_string)
            self.cursor = self.get_cursor()
            self.pid = self.conn.get_backend_pid()
            status = True
        except psycopg2.DatabaseError as e:
            self.last_error = e
            status = False

        return status

    def close_db(self):
        """Close this instance's connection only (this process)."""
        try:
            if self.cursor:
                try:
                    self.cursor.close()
                except Exception:
                    pass
            if self.conn:
                try:
                    self.conn.close()
                except Exception:
                    pass
            status = True
        except Exception as e:
            self.last_error = e
            status = False
        self.cursor = None
        self.conn = None
        self.pid = None
        return status

    def get_cursor(self, aux_conn=None):
        if aux_conn:
            cursor = aux_conn.cursor(cursor_factory=psycopg2.extras.DictCursor)
        else:
            cursor = self.conn.cursor(cursor_factory=psycopg2.extras.DictCursor)
        return cursor

    def reset_db(self):
        """Reset database connection"""
        if self.init_db():
            if self.set_search_path:
                self.execute_sql(self.set_search_path)

    def check_cursor(self):
        """Check if cursor is closed"""
        if self.cursor is None or self.cursor.closed:
            self.reset_db()
            return self.cursor is not None and not self.cursor.closed
        return True

    def cursor_execute(self, sql):
        """Check if cursor is closed before execution"""
        if self.check_cursor():
            self.cursor.execute(sql)

    def get_poll(self):
        """Check if the connection is established"""
        status = True
        try:
            if self.check_cursor():
                self.conn.poll()
        except psycopg2.InterfaceError:
            self.reset_db()
            status = False
        except psycopg2.OperationalError:
            self.reset_db()
            status = False
        return status

    def set_params(self, host, port, dbname, user, password, sslmode, connect_timeout=None):
        """Set database parameters"""
        self.host = host
        self.port = port
        self.dbname = dbname
        self.user = user
        self.password = password
        self.conn_string = f"host={self.host} port={self.port} dbname={self.dbname} user='{self.user}'"
        if sslmode:
            self.conn_string += f" sslmode={sslmode}"
        if self.password is not None:
            self.conn_string += f" password={self.password}"
        self._append_connect_options(connect_timeout)

    def set_conn_string(self, conn_string, connect_timeout=None):
        """Set connection string"""
        self.conn_string = conn_string
        self._append_connect_options(connect_timeout)

    def set_service(self, service, sslmode=None, connect_timeout=None):
        """Set service"""
        self.conn_string = f"service={service}"
        if sslmode:
            self.conn_string += f" sslmode={sslmode}"
        self._append_connect_options(connect_timeout)

    def _append_connect_options(self, connect_timeout=None):
        if connect_timeout is None:
            from . import tools_db
            connect_timeout = tools_db.get_db_connect_timeout()
        self.conn_string += (
            f" connect_timeout={int(connect_timeout)}"
            f" keepalives=1 keepalives_idle=30"
            f" application_name={self.APP_NAME_DAO}"
        )

    def _conn_string_for_app(self, application_name):
        """Same libpq string with a different application_name (this process only)."""
        token = f"application_name={self.APP_NAME_DAO}"
        replacement = f"application_name={application_name}"
        if token in self.conn_string:
            return self.conn_string.replace(token, replacement)
        return f"{self.conn_string} {replacement}"

    def mogrify(self, sql, params):
        """Return a query string after arguments binding"""
        query = sql
        try:
            cursor = self.get_cursor()
            query = cursor.mogrify(sql, params)
        except Exception as e:
            self.last_error = e
        return query

    def get_rows(self, sql, commit=False, aux_conn=None):
        """Get multiple rows from selected query"""
        self.last_error = None
        rows = None
        cursor = None
        try:
            cursor = self.get_cursor(aux_conn)
            cursor.execute(sql)
            rows = cursor.fetchall()
            if commit:
                self.commit(aux_conn)
        except Exception as e:
            self.last_error = e
            if commit:
                self.rollback(aux_conn)
        finally:
            if aux_conn is None and cursor is not None and cursor is not self.cursor:
                try:
                    cursor.close()
                except Exception:
                    pass
        return rows

    def get_row(self, sql, commit=False, aux_conn=None):
        """Get single row from selected query"""
        self.last_error = None
        row = None
        cursor = None
        try:
            cursor = self.get_cursor(aux_conn)
            cursor.execute(sql)
            row = cursor.fetchone()
            if commit:
                self.commit(aux_conn)
        except Exception as e:
            self.last_error = e
            if commit:
                self.rollback(aux_conn)
        finally:
            if aux_conn is None and cursor is not None and cursor is not self.cursor:
                try:
                    cursor.close()
                except Exception:
                    pass
        return row

    def execute_sql(self, sql, commit=True, aux_conn=None):
        """Execute selected query"""
        self.last_error = None
        status = True
        try:
            cursor = self.get_cursor(aux_conn)
            cursor.execute(sql)
            if commit:
                self.commit(aux_conn)
        except Exception as e:
            self.last_error = e
            status = False
            if commit:
                self.rollback(aux_conn)
        return status

    def execute_returning(self, sql, commit=True, aux_conn=None):
        """Execute selected query and return RETURNING field"""
        self.last_error = None
        value = None
        try:
            cursor = self.get_cursor(aux_conn)
            cursor.execute(sql)
            value = cursor.fetchone()
            if commit:
                self.commit(aux_conn)
        except Exception as e:
            self.last_error = e
            self.rollback(aux_conn)
        return value

    def commit(self, aux_conn=None):
        """Commit current database transaction"""
        try:
            if aux_conn is not None:
                aux_conn.commit()
                return
            self.conn.commit()
        except Exception:
            pass

    def rollback(self, aux_conn=None):
        """Rollback current database transaction"""
        try:
            if aux_conn is not None:
                aux_conn.rollback()
                return
            self.conn.rollback()
        except Exception:
            pass

    def export_to_csv(self, sql, csv_file):
        """Dumps contents of the query to selected CSV file"""
        try:
            cursor = self.get_cursor()
            cursor.export_to_csv(sql, csv_file)
            return None
        except Exception as e:
            return e

    def cancel_pid(self, pid):
        """Cancel one process by pid"""
        # Create an auxiliary connection with the intention of being able to cancel processes of the main connection
        last_error = None
        try:
            aux_conn = psycopg2.connect(self._conn_string_for_app(self.APP_NAME_AUX))
            cursor = self.get_cursor(aux_conn)
            cursor.execute(f"SELECT pg_cancel_backend({int(pid)})")
            status = True
            cursor.close()
            aux_conn.close()
            del cursor
            del aux_conn
        except Exception as e:
            last_error = e
            status = False

        return {"status": status, "last_error": last_error}

    def get_aux_conn(self):
        """Open a short-lived extra connection for this process. None on failure."""
        try:
            aux_conn = psycopg2.connect(self._conn_string_for_app(self.APP_NAME_AUX))
            cursor = self.get_cursor(aux_conn)
            if self.set_search_path:
                cursor.execute(self.set_search_path)
                aux_conn.commit()
            return aux_conn
        except Exception as e:
            self.last_error = e
            return None

    def delete_aux_con(self, aux_conn):
        if aux_conn is None:
            return
        try:
            aux_conn.close()
        except Exception as e:
            self.last_error = e

    def check_connection(self):
        """Check database connection. Reconnect if needed.

        Ping uses autocommit so SELECT 1 does not leave idle-in-transaction.
        """
        was_closed = False
        try:
            if self.conn is None or getattr(self.conn, "closed", True):
                raise psycopg2.OperationalError("connection closed")
            old_autocommit = self.conn.autocommit
            self.conn.autocommit = True
            try:
                with self.conn.cursor() as cur:
                    cur.execute("SELECT 1")
                    cur.fetchone()
            finally:
                try:
                    self.conn.autocommit = old_autocommit
                except Exception:
                    pass
        except (psycopg2.OperationalError, psycopg2.InterfaceError):
            was_closed = True
            self.init_db()
        return was_closed
