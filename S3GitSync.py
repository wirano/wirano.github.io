#! /usr/bin/env python3
# -*- coding: utf-8 -*-
#
# Copyright © 2023 wirano <git@wirano.me>
#
# Distributed under terms of the MIT license.


import os
import boto3
import tomllib
import logging
from git import Repo

class S3GitSync:
    def __init__(self, config_path):
        self.config = self._load_config(config_path)
        self.bucket_name = self.config['bucket_name']
        self.bucket_prefix = self.config['bucket_prefix']
        self.sync_path = self.config['sync_path']
        self.log_file = self.config['log_file']
        self.git_repo_path = self._find_git_repo();
        self.s3 = boto3.client(
            service_name ="s3",
            endpoint_url = self.config['endpoint'],
            aws_access_key_id = self.config['access_key_id'],
            aws_secret_access_key = self.config['secret_access_key'],
            region_name="auto",
        )
        self.s3_objects = self._get_s3_objects()
        self.local_files = self._get_local_files()
        self.logger = self._setup_logger()
        self.repo = Repo(self.git_repo_path)

    def _load_config(self, config_path):
        with open(config_path, 'rb') as config_file:
            config = tomllib.load(config_file)
        return config

    def _find_git_repo(self):
        current_directory = os.path.abspath(self.sync_path)
        while current_directory != "/":
            git_directory = os.path.join(current_directory, ".git")
            if os.path.isdir(git_directory):
                return current_directory
            current_directory = os.path.dirname(current_directory)
        raise ValueError("No Git repository found in the parent directories.")

    def _setup_logger(self):
        logger = logging.getLogger("S3SyncWithGit")
        logger.setLevel(logging.INFO)
        formatter = logging.Formatter("%(asctime)s - %(levelname)s - %(message)s")
        file_handler = logging.FileHandler(self.log_file)
        file_handler.setFormatter(formatter)
        logger.addHandler(file_handler)
        return logger

    def _get_s3_objects(self):
        objects = {}
        response = self.s3.list_objects_v2(Bucket=self.bucket_name, Prefix=self.bucket_prefix)
        for obj in response['Contents']:
            key = obj['Key']
            last_modified = obj['LastModified']
            objects[key] = last_modified
        keys_to_delete = [key for key in objects if key.endswith('/')] # ignore dirs
        for key in keys_to_delete:
            del objects[key]
        return objects

    def _get_local_files(self):
        file_list = []
        for root, dirs, files in os.walk(self.sync_path):
            for file_name in files:
                file_path = os.path.join(root, file_name)
                file_list.append(file_path.replace(self.sync_path, ''))
        return file_list

    def _compare_local_s3(self):
        files_to_download = []
        for key in self.s3_objects:
            if key.replace(self.bucket_prefix, '') in self.local_files:
                s3_last_modified = self.s3_objects[key]
                local_path = os.path.join(self.sync_path, key.replace(self.bucket_prefix, ''))
                local_last_modified = os.path.getmtime(local_path)
                if local_last_modified < s3_last_modified.timestamp():
                    files_to_download.append(key)
            else:
                files_to_download.append(key)
        return files_to_download

    def _download_files(self, files_to_download):
        for file_path in files_to_download:
            dest_path = os.path.join(self.sync_path, file_path.replace(self.bucket_prefix, ''))
            dir_path = os.path.dirname(dest_path)
            if not os.path.exists(dir_path):
                os.makedirs(dir_path)
            self.s3.download_file(self.bucket_name, file_path, dest_path)
            self.logger.info(file_path)

    def _commit_and_push_changes(self):
        repo = self.repo
        repo.git.add(A=True)
        repo.git.commit('-m', 'Sync files with S3')
        repo.git.push()

    def compare_and_sync(self):
        self.logger.info("Starting synchronization...")
        files_to_download = self._compare_local_s3()
        if not files_to_download:
            self.logger.info("No file need to sync")
            return
        self._download_files(files_to_download)
        self.logger.info("S3 synchronization completed.")
        #  self._commit_and_push_changes()
        self.logger.info("Git synchronization  completed.")

if __name__ == '__main__':
    config = "./sync_config.toml"
    sync = S3GitSync(config)
    sync.compare_and_sync()

